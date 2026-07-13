"""Lazy dispatch from persisted trends to a configured AI generation pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.utils.module_loading import import_string

from .contracts import AbstractAIGenerationPipeline, TrendGenerationRequest
from .normalization import unique_strings

if TYPE_CHECKING:
    from core.models import Trend


class PipelineConfigurationError(RuntimeError):
    """Raised when AI dispatch was requested but no valid adapter is configured."""


class PipelineDispatchError(RuntimeError):
    """Raised when a configured adapter cannot accept a trend request."""


class AITrendDispatcher:
    """Resolve an AI adapter lazily, avoiding imports from provider applications."""

    setting_name = "TUBEPULSE_AI_PIPELINE_CLASS"

    def __init__(
        self,
        pipeline: AbstractAIGenerationPipeline | Any | None = None,
        *,
        pipeline_path: str | None = None,
    ) -> None:
        self._pipeline = pipeline
        self.pipeline_path = pipeline_path

    def _get_pipeline(self) -> Any:
        if self._pipeline is not None:
            pipeline = self._pipeline
        else:
            path = self.pipeline_path or getattr(settings, self.setting_name, "")
            if not path:
                raise PipelineConfigurationError(
                    f"Set {self.setting_name} to a class implementing submit_trend()."
                )
            try:
                pipeline_type = import_string(path)
                pipeline = pipeline_type()
            except (ImportError, AttributeError, TypeError) as exc:
                raise PipelineConfigurationError(
                    f"Could not initialize AI trend pipeline {path!r}: {exc}"
                ) from exc
            self._pipeline = pipeline

        if not callable(getattr(pipeline, "submit_trend", None)):
            raise PipelineConfigurationError(
                "The configured AI trend pipeline must define callable submit_trend(request)."
            )
        return pipeline

    def dispatch(self, trend: Trend) -> object | None:
        """Submit one saved Trend through the provider-neutral request contract."""

        if trend.pk is None:
            raise PipelineDispatchError("A trend must be saved before it can be dispatched.")
        request = TrendGenerationRequest(
            trend_id=int(trend.pk),
            user_id=int(trend.user_id) if trend.user_id is not None else None,
            title=str(trend.title),
            niche=str(trend.niche),
            keywords=tuple(unique_strings(trend.keywords or (), limit=20)),
            source_url=str(trend.source_url or ""),
        )
        try:
            return self._get_pipeline().submit_trend(request)
        except PipelineConfigurationError:
            raise
        except Exception as exc:
            raise PipelineDispatchError(
                f"AI dispatch failed for trend {trend.pk}: {exc}"
            ) from exc
