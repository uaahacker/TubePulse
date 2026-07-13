"""Provider contract and resilient JSON-over-HTTP implementation helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ai_studio.exceptions import (
    ProviderAuthenticationError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderResponseError,
)

MessageRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class AIMessage:
    role: MessageRole
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant"}:
            raise ValueError(f"Invalid message role: {self.role}")
        if not self.content.strip():
            raise ValueError("Message content cannot be empty.")


@dataclass(frozen=True, slots=True)
class AIResponse:
    provider: str
    model: str
    content: str
    finish_reason: str | None = None
    request_id: str | None = None
    usage: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ProviderResponseError(
                f"{self.provider} returned an empty text response."
            )


class AIProvider(ABC):
    """Universal text-generation interface used by the ingestion pipeline."""

    name: str
    default_model: str

    @abstractmethod
    def generate_text(
        self,
        messages: Sequence[AIMessage],
        *,
        model: str | None = None,
        temperature: float | None = 0.7,
        max_tokens: int = 1_200,
    ) -> AIResponse:
        raise NotImplementedError


class JSONHTTPProvider(AIProvider):
    """Shared transport with bounded retries and safe error normalization."""

    endpoint: str

    def __init__(
        self,
        api_key: str,
        *,
        timeout: tuple[float, float] = (5.0, 90.0),
        session: requests.Session | None = None,
        default_model: str | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        self._api_key = api_key.strip()
        self.timeout = timeout
        self.default_model = default_model or type(self).default_model
        self._owns_session = session is None
        self.session = session or self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=8, pool_maxsize=8)
        session.mount("https://", adapter)
        return session

    def _post_json(
        self,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> tuple[dict[str, Any], Mapping[str, str]]:
        try:
            response = self.session.post(
                self.endpoint,
                json=dict(payload),
                headers=dict(headers),
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise ProviderNetworkError(
                f"{self.name} timed out while generating content. Try again."
            ) from exc
        except requests.RequestException as exc:
            raise ProviderNetworkError(
                f"Could not reach {self.name}. Check the network and try again."
            ) from exc

        try:
            if response.status_code in {401, 403}:
                raise ProviderAuthenticationError(
                    f"{self.name} rejected the API key. Update it in API Key Settings."
                )
            if response.status_code == 429:
                raise ProviderRateLimitError(
                    f"{self.name} rate or quota limit was reached. Try again later."
                )
            if not 200 <= response.status_code < 300:
                detail = self._safe_error_detail(response)
                raise ProviderResponseError(
                    f"{self.name} returned HTTP {response.status_code}: {detail}"
                )
            try:
                body = response.json()
            except (requests.JSONDecodeError, ValueError) as exc:
                raise ProviderResponseError(
                    f"{self.name} returned a non-JSON response."
                ) from exc
            if not isinstance(body, dict):
                raise ProviderResponseError(
                    f"{self.name} returned an unexpected response object."
                )
            return body, dict(response.headers)
        finally:
            response.close()

    @staticmethod
    def _safe_error_detail(response: requests.Response) -> str:
        detail = "Request failed"
        try:
            payload = response.json()
            error = payload.get("error", payload) if isinstance(payload, dict) else payload
            if isinstance(error, dict):
                detail = str(error.get("message") or error.get("detail") or detail)
            elif isinstance(error, str):
                detail = error
        except (requests.JSONDecodeError, ValueError):
            if response.text:
                detail = response.text
        return " ".join(detail.split())[:500]

    @staticmethod
    def _validate_request(
        messages: Sequence[AIMessage], max_tokens: int, temperature: float | None
    ) -> None:
        if not messages:
            raise ValueError("At least one message is required.")
        if max_tokens < 1 or max_tokens > 128_000:
            raise ValueError("max_tokens must be between 1 and 128000.")
        if temperature is not None and not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2.")

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def __enter__(self) -> "JSONHTTPProvider":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
