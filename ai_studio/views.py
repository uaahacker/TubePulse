"""Authenticated entry points for AI-assisted video project creation."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from urllib.parse import urlparse

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.conf import settings
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core.models import Trend, VideoProject

from .exceptions import AIStudioError
from .generation import TrendGenerationPipeline
from .providers.factory import supported_providers
from .video.assets import AssetResolver

logger = logging.getLogger(__name__)


def _visible_trends(user):
    return Trend.objects.filter(is_active=True).filter(
        Q(user=user) | Q(user__isnull=True)
    )


@login_required
@require_http_methods(["GET", "POST"])
def create_project(request):
    """Create a project from a visible trend and generate its content package."""

    trend_id = request.POST.get("trend_id") if request.method == "POST" else request.GET.get("trend_id")
    selected_provider = (
        request.POST.get("provider")
        if request.method == "POST"
        else request.GET.get("provider", "openai")
    )
    selected_provider = (selected_provider or "openai").strip().lower()
    provider_names = supported_providers()

    if request.method == "GET":
        trend = (
            get_object_or_404(_visible_trends(request.user), pk=trend_id)
            if trend_id
            else None
        )
        return render(
            request,
            "ai_studio/create_project.html",
            {
                "trend": trend,
                "trends": _visible_trends(request.user).order_by(
                    "-score", "-discovered_at"
                )[:50],
                "providers": provider_names,
                "selected_provider": (
                    selected_provider if selected_provider in provider_names else "openai"
                ),
            },
        )

    if not trend_id:
        messages.error(request, "Choose a trend before generating a video project.")
        return redirect("dashboard:trends")
    if selected_provider not in provider_names:
        messages.error(request, "Choose a supported AI provider.")
        return redirect(f"{request.path}?trend_id={trend_id}")

    trend = get_object_or_404(_visible_trends(request.user), pk=trend_id)
    project = VideoProject.objects.create(
        user=request.user,
        trend=trend,
        title=trend.title[:200],
        provider=selected_provider,
        status=VideoProject.Status.SCRIPTING,
        progress=10,
    )
    try:
        package = TrendGenerationPipeline(
            provider_name=selected_provider,
            user=request.user,
        ).generate_from_trend(trend)
        project.script = package.script
        project.voiceover_prompt = package.voiceover_prompt
        project.status = VideoProject.Status.READY
        project.progress = 35
        project.error_message = ""
        project.save(
            update_fields=[
                "script",
                "voiceover_prompt",
                "status",
                "progress",
                "error_message",
                "updated_at",
            ]
        )
        trend.status = Trend.Status.QUEUED
        trend.save(update_fields=["status", "updated_at"])
    except AIStudioError as exc:
        project.mark_failed(str(exc))
        messages.error(request, str(exc))
        return redirect("dashboard:queue")
    except (TypeError, ValueError) as exc:
        project.mark_failed(str(exc))
        messages.error(request, f"The trend could not be generated: {exc}")
        return redirect("dashboard:queue")
    except Exception:
        logger.exception("Unexpected content-generation failure for project %s", project.pk)
        safe_message = "Content generation failed unexpectedly. Try again or choose another provider."
        project.mark_failed(safe_message)
        messages.error(request, safe_message)
        return redirect("dashboard:queue")

    messages.success(
        request,
        f'Script and voice direction generated for "{project.title}".',
    )
    return redirect("dashboard:queue")


@login_required
@require_POST
def queue_project_render(request, public_id):
    """Record a render request quickly; the queue worker performs FFmpeg work."""

    project = get_object_or_404(VideoProject, public_id=public_id, user=request.user)
    if project.status not in {VideoProject.Status.READY, VideoProject.Status.FAILED}:
        messages.warning(
            request,
            f"This project is {project.get_status_display().lower()} and cannot be queued.",
        )
        return redirect("dashboard:queue")
    if not project.script.strip():
        messages.error(request, "Generate a script before requesting a render.")
        return redirect("dashboard:queue")

    new_assets: list[object] = []
    stored_names: list[str] = []
    old_asset_storage_names = [
        str(item["storage_name"])
        for item in (project.source_assets or [])
        if isinstance(item, dict) and item.get("storage_name")
    ]
    new_audio_name = ""
    old_audio_name = project.audio_file.name
    try:
        asset_urls = _posted_asset_urls(request)
        asset_uploads = request.FILES.getlist("assets")
        audio_upload = request.FILES.get("audio")
        if len(asset_urls) + len(asset_uploads) > 12:
            raise ValueError("Use at most 12 background assets per project.")
        for raw_url in asset_urls:
            if len(raw_url) > 2_000:
                raise ValueError("Asset URLs cannot exceed 2,000 characters.")
            parsed = urlparse(raw_url)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username:
                raise ValueError(f"Invalid public asset URL: {raw_url}")
            new_assets.append(raw_url)

        max_bytes = int(settings.TUBEPULSE_MAX_DOWNLOAD_MB) * 1024 * 1024
        uploaded_bytes = sum(upload.size for upload in asset_uploads)
        if audio_upload is not None:
            uploaded_bytes += audio_upload.size
        if uploaded_bytes > max_bytes:
            raise ValueError(
                "Combined narration and background uploads exceed the "
                f"{settings.TUBEPULSE_MAX_DOWNLOAD_MB} MB request limit."
            )
        allowed_suffixes = AssetResolver.VIDEO_SUFFIXES | AssetResolver.IMAGE_SUFFIXES
        for upload in asset_uploads:
            suffix = Path(upload.name).suffix.lower()
            if suffix not in allowed_suffixes:
                raise ValueError(f"Unsupported uploaded asset format: {suffix or 'unknown'}")
            if upload.size > max_bytes:
                raise ValueError(
                    f"{upload.name} exceeds the {settings.TUBEPULSE_MAX_DOWNLOAD_MB} MB limit."
                )
            storage_name = default_storage.save(
                (
                    f"users/{request.user.pk}/projects/{project.public_id}/assets/"
                    f"{uuid.uuid4().hex}{suffix}"
                ),
                upload,
            )
            stored_names.append(storage_name)
            media_type = "video" if suffix in AssetResolver.VIDEO_SUFFIXES else "image"
            new_assets.append(
                {"storage_name": storage_name, "media_type": media_type}
            )

        if audio_upload is not None:
            audio_suffix = Path(audio_upload.name).suffix.lower()
            allowed_audio = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}
            if audio_suffix not in allowed_audio:
                raise ValueError(
                    f"Unsupported narration audio format: {audio_suffix or 'unknown'}"
                )
            if audio_upload.size > max_bytes:
                raise ValueError(
                    f"{audio_upload.name} exceeds the {settings.TUBEPULSE_MAX_DOWNLOAD_MB} MB limit."
                )
            content_type = (audio_upload.content_type or "").lower()
            if content_type and not (
                content_type.startswith("audio/")
                or content_type in {"application/octet-stream", "video/mp4"}
            ):
                raise ValueError("The narration upload is not recognized as audio.")
            project.audio_file.save(audio_upload.name, audio_upload, save=False)
            new_audio_name = project.audio_file.name

        if new_assets:
            project.source_assets = new_assets
        project.status = VideoProject.Status.QUEUED
        project.progress = 40
        project.error_message = ""
        project.save(
            update_fields=[
                "source_assets",
                "audio_file",
                "status",
                "progress",
                "error_message",
                "updated_at",
            ]
        )
    except (OSError, ValueError) as exc:
        _cleanup_new_uploads(project, stored_names, new_audio_name)
        messages.error(request, str(exc))
        return redirect("dashboard:queue")
    except Exception:
        logger.exception("Could not queue render assets for project %s", project.pk)
        _cleanup_new_uploads(project, stored_names, new_audio_name)
        messages.error(request, "The render request could not be saved. Try again.")
        return redirect("dashboard:queue")

    if new_audio_name and old_audio_name and old_audio_name != new_audio_name:
        _safe_storage_delete(project.audio_file.storage, old_audio_name)
    if new_assets:
        for storage_name in old_asset_storage_names:
            if storage_name not in stored_names:
                _safe_storage_delete(default_storage, storage_name)

    messages.success(
        request,
        "Render queued. The video worker will process it in the background.",
    )
    return redirect("dashboard:queue")


def _posted_asset_urls(request) -> list[str]:
    values = request.POST.getlist("asset_url")
    values.extend(request.POST.get("asset_urls", "").splitlines())
    return [value.strip() for value in values if value.strip()]


def _cleanup_new_uploads(
    project: VideoProject, asset_names: list[str], audio_name: str
) -> None:
    for storage_name in asset_names:
        _safe_storage_delete(default_storage, storage_name)
    if audio_name:
        _safe_storage_delete(project.audio_file.storage, audio_name)


def _safe_storage_delete(storage, name: str) -> None:
    try:
        storage.delete(name)
    except Exception:
        logger.warning("Could not delete uploaded media %s", name, exc_info=True)
