"""Public service surface for the trend-ingestion application."""

from .contracts import (
    AbstractAIGenerationPipeline,
    AbstractTrendSource,
    TrendCandidate,
    TrendGenerationRequest,
)
from .dispatch import AITrendDispatcher
from .ingestion import IngestionReport, TrendIngestionService
from .sources import GoogleTrendsRSSSource, YouTubePublicRSSSource, build_sources

__all__ = [
    "AITrendDispatcher",
    "AbstractAIGenerationPipeline",
    "AbstractTrendSource",
    "GoogleTrendsRSSSource",
    "IngestionReport",
    "TrendCandidate",
    "TrendGenerationRequest",
    "TrendIngestionService",
    "YouTubePublicRSSSource",
    "build_sources",
]
