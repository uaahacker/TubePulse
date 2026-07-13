"""Background-runner-friendly entry points with JSON-serializable results."""

from __future__ import annotations

from collections.abc import Iterable

from django.contrib.auth import get_user_model

from .services.ingestion import TrendIngestionService
from .services.sources import build_sources


def ingest_trends_task(
    niches: Iterable[str],
    *,
    geo: str = "US",
    source_names: Iterable[str] | None = None,
    limit_per_source: int = 20,
    user_id: int | None = None,
    dispatch_ai: bool = False,
    redispatch_existing: bool = False,
) -> dict[str, object]:
    """Execute ingestion synchronously; safe to call from any task queue."""

    user = None
    if user_id is not None:
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None:
            raise ValueError(f"User {user_id} does not exist.")
    service = TrendIngestionService(sources=build_sources(source_names))
    report = service.run(
        niches,
        geo=geo,
        limit_per_source=limit_per_source,
        user=user,
        dispatch_ai=dispatch_ai,
        redispatch_existing=redispatch_existing,
    )
    return report.as_dict()
