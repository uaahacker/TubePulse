"""Reliable public RSS sources used by TubePulse trend ingestion."""

from __future__ import annotations

import calendar
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Iterable
from urllib.parse import urlencode

import feedparser
import requests

from .contracts import AbstractTrendSource, TrendCandidate
from .normalization import (
    extract_keywords,
    niche_relevance,
    normalize_title,
    parse_traffic,
    plain_text,
    traffic_score,
)

DEFAULT_TIMEOUT = (5.0, 20.0)
DEFAULT_USER_AGENT = (
    "TubePulseCRM/1.0 (+local trend research; public RSS; contact: administrator)"
)


class SourceFetchError(RuntimeError):
    """A safe, user-displayable error raised when an external source fails."""


def _entry_datetime(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)
    text = entry.get("published") or entry.get("updated")
    if not text:
        return None
    try:
        result = parsedate_to_datetime(str(text))
    except (TypeError, ValueError, OverflowError):
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


class _RSSSource(AbstractTrendSource):
    """Base implementation for HTTP retrieval and defensive RSS parsing."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    ) -> None:
        self._owns_session = session is None
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.setdefault("User-Agent", DEFAULT_USER_AGENT)
        self.session.headers.setdefault(
            "Accept", "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8"
        )

    def _parse_url(self, url: str) -> list[Any]:
        response: requests.Response | None = None
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            content = response.content
        except requests.RequestException as exc:
            raise SourceFetchError(f"{self.source_name} request failed: {exc}") from exc
        finally:
            if response is not None:
                response.close()

        parsed = feedparser.parse(content)
        entries = list(parsed.entries)
        if bool(getattr(parsed, "bozo", False)) and not entries:
            detail = str(getattr(parsed, "bozo_exception", "invalid RSS response"))
            raise SourceFetchError(f"{self.source_name} returned invalid RSS: {detail}")
        return entries

    def close(self) -> None:
        if self._owns_session:
            self.session.close()


class GoogleTrendsRSSSource(_RSSSource):
    """Country-level daily trends from Google's unauthenticated RSS feed."""

    source_name = "google_trends"
    endpoint = "https://trends.google.com/trending/rss"

    def fetch(self, niche: str, *, geo: str = "US", limit: int = 20) -> list[TrendCandidate]:
        params = urlencode({"geo": geo.upper()})
        entries = self._parse_url(f"{self.endpoint}?{params}")
        candidates: list[TrendCandidate] = []
        for entry in entries:
            title = normalize_title(entry.get("title"))
            if not title:
                continue
            summary = plain_text(entry.get("summary") or entry.get("description"))
            related_news = " ".join(
                normalize_title(item.get("news_item_title"))
                for item in entry.get("ht_news_item", [])
                if isinstance(item, dict)
            )
            relevance = niche_relevance(niche, title, summary, related_news)
            if relevance <= 0:
                continue
            traffic_text = entry.get("ht_approx_traffic", "")
            traffic = parse_traffic(traffic_text)
            published_at = _entry_datetime(entry)
            link = normalize_title(entry.get("link"))
            candidates.append(
                TrendCandidate(
                    title=title,
                    niche=normalize_title(niche),
                    source=self.source_name,
                    source_url=link,
                    keywords=extract_keywords(title, summary, related_news),
                    score=traffic_score(traffic, relevance=relevance),
                    published_at=published_at,
                    raw_payload={
                        "approx_traffic": traffic,
                        "approx_traffic_label": normalize_title(traffic_text),
                        "geo": geo.upper(),
                        "published_at": published_at.isoformat() if published_at else None,
                        "summary": summary[:1000],
                    },
                )
            )
            if len(candidates) >= limit:
                break
        return candidates


class YouTubePublicRSSSource(_RSSSource):
    """Niche-specific public RSS coverage of viral YouTube and Shorts topics.

    YouTube does not expose an unauthenticated global trending RSS feed. This
    source therefore uses Google News' public RSS search endpoint to discover
    current reporting and indexed pages about YouTube/Shorts in a niche without
    scraping a logged-in page or requiring an API key.
    """

    source_name = "youtube_public_rss"
    endpoint = "https://news.google.com/rss/search"

    def fetch(self, niche: str, *, geo: str = "US", limit: int = 20) -> list[TrendCandidate]:
        language = "en"
        region = geo.upper()
        query = f'"{normalize_title(niche)}" (YouTube OR "YouTube Shorts") (viral OR trending)'
        params = urlencode(
            {
                "q": query,
                "hl": f"{language}-{region}",
                "gl": region,
                "ceid": f"{region}:{language}",
            }
        )
        entries = self._parse_url(f"{self.endpoint}?{params}")
        candidates: list[TrendCandidate] = []
        now = datetime.now(UTC)
        for position, entry in enumerate(entries[:limit]):
            title = normalize_title(entry.get("title"))
            if not title:
                continue
            summary = plain_text(entry.get("summary") or entry.get("description"))
            published_at = _entry_datetime(entry)
            age_hours = (
                max(0.0, (now - published_at).total_seconds() / 3600.0)
                if published_at
                else 168.0
            )
            recency = max(0.0, 1.0 - min(age_hours, 336.0) / 336.0)
            position_weight = max(0.0, 1.0 - position / max(limit, 1))
            score = round(35.0 + recency * 45.0 + position_weight * 20.0, 2)
            link = normalize_title(entry.get("link"))
            candidates.append(
                TrendCandidate(
                    title=title,
                    niche=normalize_title(niche),
                    source=self.source_name,
                    source_url=link,
                    keywords=extract_keywords(title, summary, niche),
                    score=min(100.0, score),
                    published_at=published_at,
                    raw_payload={
                        "feed_rank": position + 1,
                        "geo": region,
                        "published_at": published_at.isoformat() if published_at else None,
                        "publisher": normalize_title(entry.get("source", {}).get("title"))
                        if isinstance(entry.get("source"), dict)
                        else "",
                        "summary": summary[:1000],
                    },
                )
            )
        return candidates


SOURCE_TYPES: dict[str, type[AbstractTrendSource]] = {
    GoogleTrendsRSSSource.source_name: GoogleTrendsRSSSource,
    YouTubePublicRSSSource.source_name: YouTubePublicRSSSource,
}


def build_sources(
    names: Iterable[str] | None = None,
    *,
    session: requests.Session | None = None,
) -> list[AbstractTrendSource]:
    """Instantiate a validated list of source adapters."""

    selected = list(names) if names is not None else list(SOURCE_TYPES)
    unknown = sorted(set(selected) - set(SOURCE_TYPES))
    if unknown:
        raise ValueError(f"Unknown trend source(s): {', '.join(unknown)}")
    return [SOURCE_TYPES[name](session=session) for name in selected]
