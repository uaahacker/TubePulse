"""Django orchestration for claiming, rendering, and persisting VideoProjects."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.utils import timezone

from core.models import VideoProject

from .credentials import APIKeyRepository, DjangoAPIKeyRepository
from .exceptions import AIStudioError, VideoRenderError
from .video.assets import AssetDownloader, AssetResolver, StockAssetReference
from .video.pipeline import RenderResult, VerticalVideoPipeline


def render_video_project(
    project: VideoProject,
    *,
    pipeline: VerticalVideoPipeline | None = None,
    asset_sources: Iterable[Any] | None = None,
    stock_query: str | None = None,
    audio_path: str | Path | None = None,
    output_path: str | Path | None = None,
    duration: float | None = None,
    pexels_api_key: str | None = None,
    key_repository: APIKeyRepository | None = None,
    allow_retry: bool = False,
    progress_logger: Any = None,
) -> RenderResult:
    """Atomically claim a READY project, render it, and save its FileField.

    Conditional claiming prevents two queue workers from rendering the same row.
    Known failures are recorded on the project before being re-raised.
    """

    if not project.pk:
        raise ValueError("The VideoProject must be saved before rendering.")
    allowed_statuses = [VideoProject.Status.READY, VideoProject.Status.QUEUED]
    if allow_retry:
        allowed_statuses.append(VideoProject.Status.FAILED)
    claimed = VideoProject.objects.filter(
        pk=project.pk, status__in=allowed_statuses
    ).update(
        status=VideoProject.Status.RENDERING,
        progress=45,
        error_message="",
        updated_at=timezone.now(),
    )
    if claimed != 1:
        project.refresh_from_db()
        raise VideoRenderError(
            f"Project is {project.get_status_display().lower()}, not ready to render."
        )
    project.refresh_from_db()
    if not project.script.strip():
        error = VideoRenderError("Generate a script before rendering this project.")
        project.mark_failed(str(error))
        raise error

    repository = key_repository or DjangoAPIKeyRepository()
    configured_sources = list(
        asset_sources if asset_sources is not None else (project.source_assets or [])
    )
    try:
        with tempfile.TemporaryDirectory(prefix="tubepulse-project-") as directory:
            workdir = Path(directory)
            sources, persisted_sources = _materialize_sources(
                configured_sources, workdir / "inputs"
            )
            selected_query = stock_query or (
                project.trend.title if project.trend_id else project.title
            )
            selected_pexels_key = pexels_api_key
            if not sources and not selected_pexels_key:
                selected_pexels_key = repository.get(project.user, "pexels")
            selected_audio = _materialize_audio(project, audio_path, workdir)
            render_target = (
                Path(output_path).expanduser().resolve()
                if output_path is not None
                else workdir / "project-render.mp4"
            )

            if pipeline is None:
                max_bytes = int(settings.TUBEPULSE_MAX_DOWNLOAD_MB) * 1024 * 1024
                with AssetDownloader(max_bytes=max_bytes) as downloader:
                    resolver = AssetResolver(downloader)
                    active_pipeline = VerticalVideoPipeline(
                        ffmpeg_threads=int(settings.TUBEPULSE_FFMPEG_THREADS),
                        asset_resolver=resolver,
                    )
                    result = _run_pipeline(
                        active_pipeline,
                        project=project,
                        render_target=render_target,
                        sources=sources,
                        stock_query=selected_query,
                        pexels_api_key=selected_pexels_key,
                        audio_path=selected_audio,
                        duration=duration,
                        progress_logger=progress_logger,
                    )
            else:
                result = _run_pipeline(
                    pipeline,
                    project=project,
                    render_target=render_target,
                    sources=sources,
                    stock_query=selected_query,
                    pexels_api_key=selected_pexels_key,
                    audio_path=selected_audio,
                    duration=duration,
                    progress_logger=progress_logger,
                )

            old_video_name = project.video_file.name
            new_video_name = ""
            try:
                with result.output_path.open("rb") as rendered_file:
                    project.video_file.save(
                        f"{project.public_id}.mp4",
                        File(rendered_file),
                        save=False,
                    )
                new_video_name = project.video_file.name
                if not persisted_sources and result.attributions:
                    persisted_sources = [
                        attribution.source_url
                        for attribution in result.attributions
                        if attribution.source_url
                    ]
                project.source_assets = persisted_sources
                project.status = VideoProject.Status.RENDERED
                project.progress = 100
                project.error_message = ""
                project.save(
                    update_fields=[
                        "video_file",
                        "source_assets",
                        "status",
                        "progress",
                        "error_message",
                        "updated_at",
                    ]
                )
            except Exception:
                if new_video_name:
                    project.video_file.storage.delete(new_video_name)
                raise
            if old_video_name and old_video_name != project.video_file.name:
                project.video_file.storage.delete(old_video_name)

            if output_path is None:
                try:
                    stored_path = Path(project.video_file.path)
                except (NotImplementedError, AttributeError):
                    stored_path = Path(project.video_file.name)
                result = replace(result, output_path=stored_path)
            return result
    except (AIStudioError, ValueError) as exc:
        project.mark_failed(str(exc))
        raise
    except Exception as exc:
        safe_error = VideoRenderError(
            "Project rendering failed while reading media or saving the result."
        )
        project.mark_failed(str(safe_error))
        raise safe_error from exc


def _run_pipeline(
    pipeline: VerticalVideoPipeline,
    *,
    project: VideoProject,
    render_target: Path,
    sources: list[Any],
    stock_query: str,
    pexels_api_key: str | None,
    audio_path: Path | None,
    duration: float | None,
    progress_logger: Any,
) -> RenderResult:
    return pipeline.render(
        script=project.script,
        output_path=render_target,
        audio_path=audio_path,
        asset_sources=sources,
        stock_query=stock_query,
        pexels_api_key=pexels_api_key,
        duration=duration,
        progress_logger=progress_logger,
    )


def _materialize_sources(
    values: list[Any], destination: Path
) -> tuple[list[Any], list[Any]]:
    destination.mkdir(parents=True, exist_ok=True)
    sources: list[Any] = []
    persisted: list[Any] = []
    for value in values:
        if isinstance(value, StockAssetReference):
            sources.append(value)
            persisted.append(value.url)
            continue
        if isinstance(value, Mapping):
            if value.get("storage_name"):
                storage_name = str(value["storage_name"])
                sources.append(_materialize_storage_file(storage_name, destination))
                persisted.append(dict(value))
                continue
            raw = value.get("url") or value.get("path")
            if not raw:
                raise ValueError("Source asset objects require url, path, or storage_name.")
            media_type = value.get("media_type")
            if media_type in {"image", "video"} and str(raw).startswith(("http://", "https://")):
                sources.append(StockAssetReference(str(raw), media_type))
            else:
                sources.append(str(raw))
            persisted.append(dict(value))
            continue
        sources.append(value)
        persisted.append(str(value))
    return sources, persisted


def _materialize_storage_file(storage_name: str, destination: Path) -> Path:
    try:
        return Path(default_storage.path(storage_name))
    except (NotImplementedError, AttributeError):
        target = destination / Path(storage_name).name
        with default_storage.open(storage_name, "rb") as source, target.open("wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
        return target


def _materialize_audio(
    project: VideoProject, explicit_path: str | Path | None, workdir: Path
) -> Path | None:
    if explicit_path is not None:
        return Path(explicit_path).expanduser().resolve()
    if not project.audio_file:
        return None
    try:
        return Path(project.audio_file.path)
    except (NotImplementedError, AttributeError):
        suffix = Path(project.audio_file.name).suffix or ".audio"
        target = workdir / f"narration{suffix}"
        with project.audio_file.open("rb") as source, target.open("wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
        return target
