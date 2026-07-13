"""Deterministic normalization and scoring helpers for trend records."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Iterable

from bs4 import BeautifulSoup

_WHITESPACE_RE = re.compile(r"\s+")
_CANONICAL_RE = re.compile(r"[^a-z0-9]+")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#.'-]{1,39}")
_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "against",
        "been",
        "before",
        "being",
        "between",
        "could",
        "from",
        "have",
        "into",
        "more",
        "most",
        "other",
        "over",
        "shorts",
        "some",
        "than",
        "that",
        "their",
        "there",
        "these",
        "they",
        "this",
        "video",
        "viral",
        "what",
        "when",
        "where",
        "which",
        "while",
        "with",
        "would",
        "youtube",
    }
)
_USEFUL_SHORT_TOKENS = frozenset({"ai", "ar", "vr", "ux", "3d", "ev"})


def plain_text(value: object) -> str:
    """Strip markup and normalize whitespace from an RSS field."""

    soup = BeautifulSoup(str(value or ""), "html.parser")
    return normalize_title(soup.get_text(" ", strip=True))


def normalize_title(value: object) -> str:
    """Return Unicode-normalized display text with collapsed whitespace."""

    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def canonical_title(value: object) -> str:
    """Return a conservative title key that is stable across RSS sources."""

    text = normalize_title(value).casefold()
    return _CANONICAL_RE.sub(" ", text).strip()


def build_fingerprint(*, niche: str, title: str, user_id: int | None = None) -> str:
    """Build a tenant-aware, source-independent deduplication fingerprint."""

    tenant = str(user_id) if user_id is not None else "public"
    material = f"{tenant}|{canonical_title(niche)}|{canonical_title(title)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def unique_strings(values: Iterable[object], *, limit: int = 20) -> list[str]:
    """Deduplicate non-empty strings case-insensitively while preserving order."""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = normalize_title(value)
        marker = text.casefold()
        if not text or marker in seen:
            continue
        seen.add(marker)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def extract_keywords(*values: object, limit: int = 12) -> tuple[str, ...]:
    """Extract useful keyword tokens without requiring an NLP model."""

    tokens: list[str] = []
    for value in values:
        for match in _TOKEN_RE.findall(plain_text(value)):
            token = match.strip("-.'").casefold()
            if (
                (len(token) < 3 and token not in _USEFUL_SHORT_TOKENS)
                or token in _STOPWORDS
                or token.isdigit()
            ):
                continue
            tokens.append(token)
    return tuple(unique_strings(tokens, limit=limit))


def niche_relevance(niche: str, *values: object) -> float:
    """Estimate how closely an RSS item matches the requested niche."""

    niche_tokens = set(extract_keywords(niche, limit=8))
    if not niche_tokens:
        return 0.0
    item_tokens = set(extract_keywords(*values, limit=80))
    matched = {
        niche_token
        for niche_token in niche_tokens
        if any(
            niche_token == item_token
            or (
                min(len(niche_token), len(item_token)) >= 4
                and (
                    niche_token.startswith(item_token)
                    or item_token.startswith(niche_token)
                )
            )
            for item_token in item_tokens
        )
    }
    if not matched:
        return 0.0
    return min(1.0, len(matched) / len(niche_tokens))


def parse_traffic(value: object) -> int:
    """Parse Google Trends traffic strings such as ``200K+`` or ``1.5M``."""

    text = normalize_title(value).upper().replace(",", "").rstrip("+")
    match = re.search(r"(\d+(?:\.\d+)?)\s*([KMB]?)", text)
    if not match:
        return 0
    number = float(match.group(1))
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[
        match.group(2)
    ]
    return max(0, int(number * multiplier))


def traffic_score(traffic: int, *, relevance: float = 1.0) -> float:
    """Scale unbounded traffic into a stable 0-100 score."""

    if traffic <= 0:
        base = 35.0
    else:
        base = min(100.0, (math.log10(traffic + 1) / 7.0) * 100.0)
    return round(min(100.0, base * (0.6 + 0.4 * max(0.0, min(1.0, relevance)))), 2)
