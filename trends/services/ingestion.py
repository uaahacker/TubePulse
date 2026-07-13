"""Orchestration, deduplication, persistence, and optional AI dispatch."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from core.models import Trend

from .contracts import AbstractTrendSource, TrendCandidate
from .dispatch import AITrendDispatcher
from .normalization import build_fingerprint, normalize_title, unique_strings
from .sources import SourceFetchError, build_sources


@dataclass(frozen=True, slots=True)
class IngestionError:
    """One recoverable source, persistence, or dispatch failure."""

    stage: str
    detail: str
    source: str = ""
    niche: str = ""
    trend_id: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "detail": self.detail,
            "source": self.source,
            "niche": self.niche,
            "trend_id": self.trend_id,
        }


@dataclass(slots=True)
class IngestionReport:
    """Structured outcome suitable for commands, views, and background jobs."""

    niches: tuple[str, ...]
    fetched: int = 0
    normalized: int = 0
    created: int = 0
    updated: int = 0
    dispatched: int = 0
    trend_ids: list[int] = field(default_factory=list)
    errors: list[IngestionError] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return bool(self.created or self.updated) and not any(
            error.stage == "persistence" for error in self.errors
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "niches": list(self.niches),
            "fetched": self.fetched,
            "normalized": self.normalized,
            "created": self.created,
            "updated": self.updated,
            "dispatched": self.dispatched,
            "trend_ids": self.trend_ids.copy(),
            "errors": [error.as_dict() for error in self.errors],
            "succeeded": self.succeeded,
        }


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, default=str))


def _safe_source_url(value: object) -> str:
    text = normalize_title(value)[:1000]
    parsed = urlsplit(text)
    return text if parsed.scheme.lower() in {"http", "https"} and parsed.netloc else ""


def _candidate_key(candidate: TrendCandidate) -> str:
    return build_fingerprint(niche=candidate.niche, title=candidate.title)


def _merge_candidates(left: TrendCandidate, right: TrendCandidate) -> TrendCandidate:
    """Merge the same topic from multiple feeds, retaining strongest metadata."""

    winner, other = (right, left) if right.score > left.score else (left, right)
    provenance: list[dict[str, object]] = []
    for candidate in (left, right):
        existing = candidate.raw_payload.get("provenance", [])
        if isinstance(existing, list):
            provenance.extend(item for item in existing if isinstance(item, dict))
        provenance.append(
            {
                "source": candidate.source,
                "source_url": candidate.source_url,
                "score": candidate.score,
            }
        )
    deduplicated_provenance: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for item in provenance:
        marker = (str(item.get("source", "")), str(item.get("source_url", "")))
        if marker in seen:
            continue
        seen.add(marker)
        deduplicated_provenance.append(item)

    payload = dict(winner.raw_payload)
    payload["provenance"] = deduplicated_provenance
    return TrendCandidate(
        title=winner.title,
        niche=winner.niche,
        source=winner.source,
        source_url=winner.source_url,
        keywords=tuple(unique_strings((*winner.keywords, *other.keywords), limit=20)),
        score=max(left.score, right.score),
        published_at=winner.published_at or other.published_at,
        raw_payload=payload,
    )


class TrendIngestionService:
    """Fetch public feeds and upsert normalized trends into the canonical model."""

    def __init__(
        self,
        *,
        sources: Sequence[AbstractTrendSource] | None = None,
        dispatcher: AITrendDispatcher | None = None,
    ) -> None:
        self.sources = list(sources) if sources is not None else build_sources()
        self.dispatcher = dispatcher

    @staticmethod
    def _normalize_niches(niches: Iterable[str]) -> tuple[str, ...]:
        normalized = tuple(unique_strings(niches, limit=50))
        if not normalized:
            raise ValueError("At least one non-empty niche is required.")
        if any(len(niche) > 100 for niche in normalized):
            raise ValueError("Each niche must be 100 characters or fewer.")
        return normalized

    @staticmethod
    def _persist(candidate: TrendCandidate, *, user: Any | None) -> tuple[Trend, bool]:
        niche = normalize_title(candidate.niche)[:100]
        title = normalize_title(candidate.title)[:300]
        source = normalize_title(candidate.source)[:80] or "unknown"
        keywords = unique_strings(
            (normalize_title(keyword)[:100] for keyword in candidate.keywords),
            limit=20,
        )
        fingerprint = build_fingerprint(
            niche=niche,
            title=title,
            user_id=int(user.pk) if user is not None else None,
        )
        defaults = {
            "user": user,
            "niche": niche,
            "title": title,
            "keywords": keywords,
            "source": source,
            "source_url": _safe_source_url(candidate.source_url),
            "score": int(round(max(0.0, min(100.0, float(candidate.score))))),
            "raw_payload": _json_safe(dict(candidate.raw_payload)),
            "is_active": True,
        }
        with transaction.atomic():
            trend, created = Trend.objects.get_or_create(
                fingerprint=fingerprint,
                defaults=defaults,
            )
            if created:
                return trend, True

            stored_score = float(trend.score or 0.0)
            trend.keywords = unique_strings(
                (*(trend.keywords or []), *keywords), limit=20
            )
            trend.is_active = True
            trend.raw_payload = defaults["raw_payload"]
            update_fields = ["keywords", "is_active", "raw_payload", "updated_at"]
            if float(defaults["score"]) >= stored_score:
                trend.niche = str(defaults["niche"])
                trend.title = str(defaults["title"])
                trend.source = str(defaults["source"])
                trend.source_url = str(defaults["source_url"])
                trend.score = int(defaults["score"])
                update_fields.extend(["niche", "title", "source", "source_url", "score"])
            trend.save(update_fields=update_fields)
            return trend, False

    def run(
        self,
        niches: Iterable[str],
        *,
        geo: str = "US",
        limit_per_source: int = 20,
        user: Any | None = None,
        dispatch_ai: bool = False,
        redispatch_existing: bool = False,
    ) -> IngestionReport:
        """Run every configured source, then upsert and optionally dispatch results."""

        normalized_niches = self._normalize_niches(niches)
        if not 1 <= limit_per_source <= 100:
            raise ValueError("limit_per_source must be between 1 and 100.")
        geo = normalize_title(geo).upper()
        if len(geo) != 2 or not geo.isalpha():
            raise ValueError("geo must be a two-letter country code.")

        report = IngestionReport(niches=normalized_niches)
        candidates: dict[str, TrendCandidate] = {}
        for niche in normalized_niches:
            for source in self.sources:
                try:
                    fetched = source.fetch(niche, geo=geo, limit=limit_per_source)
                except SourceFetchError as exc:
                    report.errors.append(
                        IngestionError(
                            stage="fetch",
                            source=source.source_name,
                            niche=niche,
                            detail=str(exc),
                        )
                    )
                    continue
                except Exception as exc:
                    report.errors.append(
                        IngestionError(
                            stage="fetch",
                            source=source.source_name,
                            niche=niche,
                            detail=f"Unexpected source error: {exc}",
                        )
                    )
                    continue

                report.fetched += len(fetched)
                for candidate in fetched:
                    if not normalize_title(candidate.title):
                        continue
                    key = _candidate_key(candidate)
                    candidates[key] = (
                        _merge_candidates(candidates[key], candidate)
                        if key in candidates
                        else candidate
                    )

        for source in self.sources:
            source.close()

        report.normalized = len(candidates)
        dispatcher = self.dispatcher or AITrendDispatcher()
        for candidate in candidates.values():
            try:
                trend, created = self._persist(candidate, user=user)
            except Exception as exc:
                report.errors.append(
                    IngestionError(
                        stage="persistence",
                        source=candidate.source,
                        niche=candidate.niche,
                        detail=f"Could not save {candidate.title!r}: {exc}",
                    )
                )
                continue
            report.trend_ids.append(int(trend.pk))
            if created:
                report.created += 1
            else:
                report.updated += 1

            if dispatch_ai and (created or redispatch_existing):
                try:
                    dispatcher.dispatch(trend)
                except Exception as exc:
                    report.errors.append(
                        IngestionError(
                            stage="dispatch",
                            source=candidate.source,
                            niche=candidate.niche,
                            trend_id=int(trend.pk),
                            detail=str(exc),
                        )
                    )
                else:
                    report.dispatched += 1
        return report
