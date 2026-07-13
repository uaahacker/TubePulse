"""MoviePy/FFmpeg pipeline for production-ready 9:16 short-form video."""

from __future__ import annotations

import gc
import logging
import os
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ai_studio.exceptions import AssetError, VideoRenderError

from .assets import AssetResolver, ResolvedAsset, StockAssetReference
from .subtitles import (
    CaptionBitmapRenderer,
    CaptionCue,
    CaptionStyle,
    build_caption_cues,
    coerce_caption_cues,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AssetAttribution:
    name: str
    url: str
    source_url: str


@dataclass(frozen=True, slots=True)
class RenderResult:
    output_path: Path
    duration: float
    width: int
    height: int
    fps: int
    caption_count: int
    attributions: tuple[AssetAttribution, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["output_path"] = str(self.output_path)
        return payload


class _ClipRegistry:
    """Closes clip wrappers and their underlying FFmpeg readers in reverse order."""

    def __init__(self) -> None:
        self._clips: list[Any] = []
        self._ids: set[int] = set()

    def track(self, clip: Any) -> Any:
        if id(clip) not in self._ids:
            self._clips.append(clip)
            self._ids.add(id(clip))
        return clip

    def close(self) -> None:
        for clip in reversed(self._clips):
            close = getattr(clip, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.warning("MoviePy clip cleanup failed", exc_info=True)
        self._clips.clear()
        self._ids.clear()
        gc.collect()


class VerticalVideoPipeline:
    """Renders stock media, optional narration, and timed captions into MP4."""

    def __init__(
        self,
        *,
        frame_size: tuple[int, int] = (1080, 1920),
        fps: int = 30,
        ffmpeg_threads: int = 2,
        preset: str = "medium",
        max_duration: float = 180.0,
        asset_resolver: AssetResolver | None = None,
    ) -> None:
        width, height = frame_size
        if width < 2 or height < 2 or width % 2 or height % 2:
            raise ValueError("Video dimensions must be positive even numbers.")
        if abs(width / height - 9 / 16) > 0.001:
            raise ValueError("VerticalVideoPipeline requires an exact 9:16 frame size.")
        if not 1 <= fps <= 60:
            raise ValueError("fps must be between 1 and 60.")
        if not 1 <= ffmpeg_threads <= 32:
            raise ValueError("ffmpeg_threads must be between 1 and 32.")
        if max_duration <= 0:
            raise ValueError("max_duration must be positive.")
        self.frame_size = frame_size
        self.fps = fps
        self.ffmpeg_threads = ffmpeg_threads
        self.preset = preset
        self.max_duration = max_duration
        self.asset_resolver = asset_resolver

    def render(
        self,
        *,
        script: str,
        output_path: str | Path,
        audio_path: str | Path | None = None,
        asset_sources: Iterable[str | Path | StockAssetReference] = (),
        stock_query: str | None = None,
        pexels_api_key: str | None = None,
        caption_timings: Sequence[CaptionCue | dict[str, Any] | tuple[Any, Any, Any]] | None = None,
        caption_style: CaptionStyle | None = None,
        duration: float | None = None,
        words_per_caption: int = 6,
        progress_logger: Any = None,
    ) -> RenderResult:
        clean_script = " ".join(script.split())
        if not clean_script:
            raise ValueError("A non-empty script is required.")
        if len(clean_script) > 50_000:
            raise ValueError("The script is too long for a short-form render.")
        final_path = Path(output_path).expanduser().resolve()
        if final_path.suffix.lower() != ".mp4":
            raise ValueError("Video output_path must end in .mp4.")
        final_path.parent.mkdir(parents=True, exist_ok=True)

        registry = _ClipRegistry()
        try:
            from moviepy import (
                AudioFileClip,
                CompositeVideoClip,
                ImageClip,
                VideoFileClip,
                concatenate_videoclips,
                vfx,
            )
        except ImportError as exc:
            raise VideoRenderError(
                "MoviePy is not installed. Install the project requirements before rendering."
            ) from exc

        with tempfile.TemporaryDirectory(
            prefix=".tubepulse-render-", dir=final_path.parent
        ) as temporary_directory:
            workdir = Path(temporary_directory)
            resolver = self.asset_resolver or AssetResolver()
            try:
                audio_clip = None
                if audio_path is not None:
                    narration_path = Path(audio_path).expanduser().resolve()
                    if not narration_path.is_file():
                        raise VideoRenderError(
                            f"Narration audio does not exist: {narration_path}"
                        )
                    audio_clip = registry.track(AudioFileClip(str(narration_path)))

                render_duration = self._resolve_duration(clean_script, duration, audio_clip)
                if audio_clip is not None and audio_clip.duration > render_duration + 0.01:
                    audio_clip = registry.track(
                        audio_clip.subclipped(0, render_duration)
                    )

                assets = resolver.resolve(
                    workdir / "assets",
                    sources=asset_sources,
                    stock_query=stock_query,
                    pexels_api_key=pexels_api_key,
                )
                segments = self._build_background_segments(
                    assets,
                    render_duration,
                    registry,
                    ImageClip=ImageClip,
                    VideoFileClip=VideoFileClip,
                    vfx=vfx,
                )
                background = registry.track(
                    concatenate_videoclips(segments, method="chain")
                )
                if background.duration > render_duration + 0.001:
                    background = registry.track(
                        background.subclipped(0, render_duration)
                    )

                if caption_timings is None:
                    captions = build_caption_cues(
                        clean_script,
                        render_duration,
                        words_per_caption=words_per_caption,
                    )
                else:
                    captions = coerce_caption_cues(
                        list(caption_timings), render_duration
                    )
                bitmap_renderer = CaptionBitmapRenderer(caption_style)
                overlays = []
                for cue in captions:
                    bitmap = bitmap_renderer.render(cue.text, self.frame_size)
                    overlay = ImageClip(bitmap.pixels, transparent=True)
                    overlay = overlay.with_start(cue.start).with_duration(
                        cue.end - cue.start
                    )
                    overlay = overlay.with_position(bitmap.position)
                    overlays.append(registry.track(overlay))

                composite = registry.track(
                    CompositeVideoClip(
                        [background, *overlays],
                        size=self.frame_size,
                        bg_color=(0, 0, 0),
                        use_bgclip=True,
                    ).with_duration(render_duration)
                )
                if audio_clip is not None:
                    composite = registry.track(composite.with_audio(audio_clip))

                temporary_output = workdir / "rendered.mp4"
                temporary_audio = workdir / "render-audio.m4a"
                composite.write_videofile(
                    str(temporary_output),
                    fps=self.fps,
                    codec="libx264",
                    audio=audio_clip is not None,
                    audio_codec="aac",
                    temp_audiofile=str(temporary_audio),
                    remove_temp=True,
                    preset=self.preset,
                    threads=self.ffmpeg_threads,
                    pixel_format="yuv420p",
                    ffmpeg_params=["-movflags", "+faststart"],
                    logger=progress_logger,
                )
                if not temporary_output.is_file() or temporary_output.stat().st_size == 0:
                    raise VideoRenderError("FFmpeg completed without producing a video file.")
                os.replace(temporary_output, final_path)
                return RenderResult(
                    output_path=final_path,
                    duration=render_duration,
                    width=self.frame_size[0],
                    height=self.frame_size[1],
                    fps=self.fps,
                    caption_count=len(captions),
                    attributions=tuple(
                        AssetAttribution(
                            name=asset.attribution_name,
                            url=asset.attribution_url,
                            source_url=asset.source_url,
                        )
                        for asset in assets
                        if asset.attribution_name or asset.attribution_url
                    ),
                )
            except (AssetError, VideoRenderError, ValueError):
                raise
            except Exception as exc:
                logger.exception("Vertical video render failed")
                raise VideoRenderError(
                    "Video rendering failed. Verify the source media and FFmpeg installation."
                ) from exc
            finally:
                registry.close()
                if self.asset_resolver is None:
                    resolver.close()

    def _resolve_duration(
        self, script: str, requested: float | None, audio_clip: Any
    ) -> float:
        if requested is not None and requested <= 0:
            raise ValueError("Render duration must be positive.")
        audio_duration = float(audio_clip.duration) if audio_clip is not None else None
        if audio_duration is not None and audio_duration <= 0:
            raise VideoRenderError("Narration audio has no usable duration.")
        if requested is not None and audio_duration is not None:
            if requested > audio_duration + 0.05:
                raise ValueError("Requested duration exceeds the narration audio duration.")
            resolved = float(requested)
        elif audio_duration is not None:
            resolved = audio_duration
        elif requested is not None:
            resolved = float(requested)
        else:
            resolved = max(3.0, len(script.split()) / 2.45)
        if resolved > self.max_duration:
            raise ValueError(
                f"Render duration exceeds the {self.max_duration:g}-second safety limit."
            )
        return resolved

    def _build_background_segments(
        self,
        assets: list[ResolvedAsset],
        duration: float,
        registry: _ClipRegistry,
        *,
        ImageClip: Any,
        VideoFileClip: Any,
        vfx: Any,
    ) -> list[Any]:
        segment_length = duration / len(assets)
        segments: list[Any] = []
        for index, asset in enumerate(assets):
            start = index * segment_length
            end = duration if index == len(assets) - 1 else (index + 1) * segment_length
            required_duration = end - start
            if asset.media_type == "image":
                source = registry.track(
                    ImageClip(str(asset.path), duration=required_duration)
                )
            else:
                source = registry.track(VideoFileClip(str(asset.path), audio=False))
                if not source.duration or source.duration <= 0:
                    raise VideoRenderError(f"Video asset has no duration: {asset.path}")
            fitted = registry.track(self._cover_frame(source))
            if asset.media_type == "video":
                if fitted.duration < required_duration - 0.001:
                    fitted = registry.track(
                        fitted.with_effects([vfx.Loop(duration=required_duration)])
                    )
                elif fitted.duration > required_duration + 0.001:
                    fitted = registry.track(fitted.subclipped(0, required_duration))
                else:
                    fitted = registry.track(fitted.with_duration(required_duration))
            segments.append(fitted)
        return segments

    def _cover_frame(self, clip: Any) -> Any:
        target_width, target_height = self.frame_size
        if not clip.w or not clip.h:
            raise VideoRenderError("Background asset has invalid dimensions.")
        source_ratio = clip.w / clip.h
        target_ratio = target_width / target_height
        if source_ratio < target_ratio:
            resized = clip.resized(width=target_width)
        else:
            resized = clip.resized(height=target_height)
        return resized.cropped(
            x_center=resized.w / 2,
            y_center=resized.h / 2,
            width=target_width,
            height=target_height,
        )
