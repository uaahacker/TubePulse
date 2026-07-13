"""Safe local/remote asset resolution with optional Pexels discovery."""

from __future__ import annotations

import ipaddress
import mimetypes
import os
import socket
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

import requests

from ai_studio.exceptions import AssetError

MediaType = Literal["video", "image"]


@dataclass(frozen=True, slots=True)
class StockAssetReference:
    url: str
    media_type: MediaType | None = None
    attribution_name: str = ""
    attribution_url: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedAsset:
    path: Path
    media_type: MediaType
    source_url: str = ""
    attribution_name: str = ""
    attribution_url: str = ""


class AssetDownloader:
    """Streams public HTTP assets to disk with redirect and size controls."""

    EXTENSIONS = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        max_bytes: int = 300 * 1024 * 1024,
        timeout: tuple[float, float] = (8.0, 120.0),
        url_validator: Callable[[str], None] | None = None,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive.")
        self._owns_session = session is None
        self.session = session or requests.Session()
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.url_validator = url_validator or validate_public_url

    def download(self, reference: StockAssetReference, destination: Path) -> ResolvedAsset:
        destination.mkdir(parents=True, exist_ok=True)
        current_url = reference.url
        response: requests.Response | None = None
        try:
            for _ in range(5):
                self.url_validator(current_url)
                response = self.session.get(
                    current_url,
                    stream=True,
                    timeout=self.timeout,
                    allow_redirects=False,
                    headers={"User-Agent": "TubePulseCRM/1.0"},
                )
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    response.close()
                    response = None
                    if not location:
                        raise AssetError("Asset server returned an empty redirect.")
                    current_url = urljoin(current_url, location)
                    continue
                break
            else:
                raise AssetError("Asset download exceeded the redirect limit.")

            if response is None:
                raise AssetError("Asset server did not return a response.")
            if not 200 <= response.status_code < 300:
                raise AssetError(
                    f"Asset download returned HTTP {response.status_code}."
                )
            content_length = self._content_length(response.headers)
            if content_length is not None and content_length > self.max_bytes:
                raise AssetError("Asset is larger than the configured download limit.")

            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            media_type = reference.media_type or self._infer_media_type(
                current_url, content_type
            )
            extension = self._extension(current_url, content_type, media_type)
            filename = f"asset-{os.urandom(8).hex()}{extension}"
            final_path = destination / filename
            partial_path = destination / f".{filename}.part"
            written = 0
            try:
                with partial_path.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > self.max_bytes:
                            raise AssetError(
                                "Asset exceeded the configured download limit while streaming."
                            )
                        output.write(chunk)
                if written == 0:
                    raise AssetError("Asset server returned an empty file.")
                partial_path.replace(final_path)
            except Exception:
                partial_path.unlink(missing_ok=True)
                raise
            return ResolvedAsset(
                path=final_path,
                media_type=media_type,
                source_url=reference.url,
                attribution_name=reference.attribution_name,
                attribution_url=reference.attribution_url,
            )
        except requests.Timeout as exc:
            raise AssetError("Stock asset download timed out.") from exc
        except requests.RequestException as exc:
            raise AssetError("Could not download the stock asset.") from exc
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def _content_length(headers: Mapping[str, str]) -> int | None:
        raw_value = headers.get("Content-Length")
        if not raw_value:
            return None
        try:
            return int(raw_value)
        except ValueError:
            return None

    @classmethod
    def _extension(cls, url: str, content_type: str, media_type: MediaType) -> str:
        if content_type:
            actual_type = content_type.split("/", 1)[0]
            if actual_type in {"image", "video"} and actual_type != media_type:
                raise AssetError(
                    f"Expected a {media_type} asset but received {content_type}."
                )
            if content_type in cls.EXTENSIONS:
                return cls.EXTENSIONS[content_type]
        suffix = Path(urlparse(url).path).suffix.lower()
        permitted = (
            {".mp4", ".webm", ".mov", ".m4v"}
            if media_type == "video"
            else {".jpg", ".jpeg", ".png", ".webp"}
        )
        if suffix in permitted:
            return suffix
        guessed = mimetypes.guess_extension(content_type) if content_type else None
        if guessed in permitted:
            return str(guessed)
        raise AssetError("Asset response did not identify a supported media format.")

    @staticmethod
    def _infer_media_type(url: str, content_type: str) -> MediaType:
        category = content_type.split("/", 1)[0]
        if category in {"image", "video"}:
            return category  # type: ignore[return-value]
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix in AssetResolver.VIDEO_SUFFIXES:
            return "video"
        if suffix in AssetResolver.IMAGE_SUFFIXES:
            return "image"
        raise AssetError("Asset response did not identify whether it is image or video.")

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def __enter__(self) -> "AssetDownloader":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class PexelsClient:
    """Finds free portrait video first and falls back to portrait photography."""

    VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"
    PHOTO_SEARCH_URL = "https://api.pexels.com/v1/search"

    def __init__(
        self,
        api_key: str,
        *,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = (5.0, 30.0),
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise AssetError("A Pexels API key is required for stock discovery.")
        self.api_key = api_key.strip()
        self._owns_session = session is None
        self.session = session or requests.Session()
        self.timeout = timeout

    def search_portrait(self, query: str, *, count: int = 3) -> list[StockAssetReference]:
        clean_query = " ".join(query.split())
        if not clean_query:
            raise AssetError("A search query is required for Pexels stock discovery.")
        if not 1 <= count <= 15:
            raise ValueError("Pexels result count must be between 1 and 15.")
        videos = self._search_videos(clean_query, count)
        if len(videos) >= count:
            return videos[:count]
        photos = self._search_photos(clean_query, count - len(videos))
        results = videos + photos
        if not results:
            raise AssetError(f"Pexels returned no usable assets for '{clean_query}'.")
        return results

    def _get_json(self, url: str, params: Mapping[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.get(
                url,
                params=dict(params),
                headers={"Authorization": self.api_key},
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise AssetError("Pexels search timed out.") from exc
        except requests.RequestException as exc:
            raise AssetError("Could not reach Pexels stock search.") from exc
        try:
            if response.status_code in {401, 403}:
                raise AssetError("Pexels rejected the configured API key.")
            if not 200 <= response.status_code < 300:
                raise AssetError(f"Pexels search returned HTTP {response.status_code}.")
            payload = response.json()
            if not isinstance(payload, dict):
                raise AssetError("Pexels returned an invalid search response.")
            return payload
        except (requests.JSONDecodeError, ValueError) as exc:
            raise AssetError("Pexels returned a non-JSON search response.") from exc
        finally:
            response.close()

    def _search_videos(self, query: str, count: int) -> list[StockAssetReference]:
        payload = self._get_json(
            self.VIDEO_SEARCH_URL,
            {"query": query, "orientation": "portrait", "per_page": count},
        )
        results: list[StockAssetReference] = []
        for video in payload.get("videos", []):
            if not isinstance(video, dict):
                continue
            files = [
                item
                for item in video.get("video_files", [])
                if isinstance(item, dict)
                and item.get("file_type") == "video/mp4"
                and isinstance(item.get("link"), str)
                and item.get("link")
            ]
            if not files:
                continue
            files.sort(key=self._video_file_score)
            user = video.get("user") if isinstance(video.get("user"), dict) else {}
            results.append(
                StockAssetReference(
                    url=files[0]["link"],
                    media_type="video",
                    attribution_name=str(user.get("name") or "Pexels contributor"),
                    attribution_url=str(user.get("url") or video.get("url") or ""),
                )
            )
        return results

    @staticmethod
    def _video_file_score(item: Mapping[str, Any]) -> tuple[float, int, int]:
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        aspect = width / height if height else 100.0
        too_small = 1 if width < 720 or height < 1280 else 0
        excessive_pixels = max(0, width * height - 1080 * 1920)
        return abs(aspect - 9 / 16), too_small, excessive_pixels

    def _search_photos(self, query: str, count: int) -> list[StockAssetReference]:
        if count < 1:
            return []
        payload = self._get_json(
            self.PHOTO_SEARCH_URL,
            {"query": query, "orientation": "portrait", "per_page": count},
        )
        results: list[StockAssetReference] = []
        for photo in payload.get("photos", []):
            if not isinstance(photo, dict) or not isinstance(photo.get("src"), dict):
                continue
            source = photo["src"]
            url = source.get("portrait") or source.get("large2x") or source.get("original")
            if not isinstance(url, str) or not url:
                continue
            results.append(
                StockAssetReference(
                    url=url,
                    media_type="image",
                    attribution_name=str(photo.get("photographer") or "Pexels contributor"),
                    attribution_url=str(
                        photo.get("photographer_url") or photo.get("url") or ""
                    ),
                )
            )
        return results

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def __enter__(self) -> "PexelsClient":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class AssetResolver:
    """Normalizes supplied paths/URLs or discovers assets through Pexels."""

    VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".m4v", ".avi"}
    IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

    def __init__(self, downloader: AssetDownloader | None = None) -> None:
        self._owns_downloader = downloader is None
        self.downloader = downloader or AssetDownloader()

    def resolve(
        self,
        destination: Path,
        *,
        sources: Iterable[str | Path | StockAssetReference] = (),
        stock_query: str | None = None,
        pexels_api_key: str | None = None,
        count: int = 3,
    ) -> list[ResolvedAsset]:
        references = list(sources)
        if not references:
            if not stock_query:
                raise AssetError(
                    "Provide local/remote background assets or a Pexels stock query."
                )
            if not pexels_api_key:
                raise AssetError(
                    "Pexels stock discovery requires PEXELS_API_KEY or an explicit key."
                )
            with PexelsClient(pexels_api_key) as pexels:
                references = pexels.search_portrait(stock_query, count=count)

        resolved: list[ResolvedAsset] = []
        downloaded_paths: list[Path] = []
        downloaded_bytes = 0
        for source in references:
            if isinstance(source, StockAssetReference):
                downloaded = self.downloader.download(source, destination)
                downloaded_paths.append(downloaded.path)
                downloaded_bytes += downloaded.path.stat().st_size
                self._enforce_aggregate_budget(downloaded_bytes, downloaded_paths)
                resolved.append(downloaded)
                continue
            raw = str(source)
            parsed = urlparse(raw)
            if parsed.scheme.lower() in {"http", "https"}:
                try:
                    media_type = self._media_type_from_suffix(Path(parsed.path).suffix)
                except AssetError:
                    media_type = None
                downloaded = self.downloader.download(
                    StockAssetReference(raw, media_type), destination
                )
                downloaded_paths.append(downloaded.path)
                downloaded_bytes += downloaded.path.stat().st_size
                self._enforce_aggregate_budget(downloaded_bytes, downloaded_paths)
                resolved.append(downloaded)
                continue
            path = Path(source).expanduser().resolve()
            if not path.is_file():
                raise AssetError(f"Background asset does not exist: {path}")
            resolved.append(
                ResolvedAsset(path=path, media_type=self._media_type_from_suffix(path.suffix))
            )
        if not resolved:
            raise AssetError("No usable background assets were resolved.")
        return resolved

    def _enforce_aggregate_budget(
        self, downloaded_bytes: int, downloaded_paths: list[Path]
    ) -> None:
        if downloaded_bytes <= self.downloader.max_bytes:
            return
        for path in downloaded_paths:
            path.unlink(missing_ok=True)
        raise AssetError(
            "Combined stock assets exceed the configured download budget."
        )

    def close(self) -> None:
        if self._owns_downloader:
            self.downloader.close()

    def __enter__(self) -> "AssetResolver":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @classmethod
    def _media_type_from_suffix(cls, suffix: str) -> MediaType:
        normalized = suffix.lower()
        if normalized in cls.VIDEO_SUFFIXES:
            return "video"
        if normalized in cls.IMAGE_SUFFIXES:
            return "image"
        raise AssetError(f"Unsupported background media format: {suffix or 'unknown'}")


def validate_public_url(url: str) -> None:
    """Reject local/private targets to keep user-supplied URLs from becoming SSRF."""

    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise AssetError("Asset URLs must use public HTTP or HTTPS addresses.")
    try:
        default_port = 443 if parsed.scheme.lower() == "https" else 80
        addresses = socket.getaddrinfo(
            parsed.hostname, parsed.port or default_port, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise AssetError("Asset hostname could not be resolved.") from exc
    if not addresses:
        raise AssetError("Asset hostname did not resolve to an address.")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_unspecified
            or ip.is_multicast
        ):
            raise AssetError("Private or local asset URLs are not allowed.")
