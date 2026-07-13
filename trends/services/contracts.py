"""Typed contracts shared by trend sources and AI-generation adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class TrendCandidate:
    """A normalized, not-yet-persisted item returned by a public source."""

    title: str
    niche: str
    source: str
    source_url: str
    keywords: tuple[str, ...] = ()
    score: float = 0.0
    published_at: datetime | None = None
    raw_payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TrendGenerationRequest:
    """Serializable boundary between trend ingestion and AI generation."""

    trend_id: int
    user_id: int | None
    title: str
    niche: str
    keywords: tuple[str, ...]
    source_url: str

    def as_dict(self) -> dict[str, object]:
        """Return a queue-safe representation of this request."""

        return {
            "trend_id": self.trend_id,
            "user_id": self.user_id,
            "title": self.title,
            "niche": self.niche,
            "keywords": list(self.keywords),
            "source_url": self.source_url,
        }


class AbstractTrendSource(ABC):
    """Interface implemented by every external trend source."""

    source_name: str

    @abstractmethod
    def fetch(self, niche: str, *, geo: str, limit: int) -> list[TrendCandidate]:
        """Fetch and normalize at most ``limit`` trends for ``niche``."""

        raise NotImplementedError("Trend sources must implement fetch().")

    def close(self) -> None:
        """Release source-owned network resources; injected sources may no-op."""

        return None


class AbstractAIGenerationPipeline(ABC):
    """Minimal adapter API required by the ingestion dispatcher."""

    @abstractmethod
    def submit_trend(self, request: TrendGenerationRequest) -> str | None:
        """Enqueue or synchronously start generation for a saved trend."""

        raise NotImplementedError("AI pipeline adapters must implement submit_trend().")
