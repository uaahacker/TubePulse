"""Stable application exceptions for provider and rendering failures."""


class AIStudioError(Exception):
    """Base class for errors that can be shown safely by the CRM."""


class MissingAPIKeyError(AIStudioError):
    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(
            f"No {provider} API key is configured. Add it on the API Key Settings page."
        )


class CredentialAccessError(AIStudioError):
    """A stored encrypted credential exists but cannot be read safely."""


class UnsupportedProviderError(AIStudioError):
    def __init__(self, provider: str, supported: tuple[str, ...]) -> None:
        self.provider = provider
        self.supported = supported
        super().__init__(
            f"Unsupported AI provider '{provider}'. Choose one of: {', '.join(supported)}."
        )


class ProviderNetworkError(AIStudioError):
    """The provider could not be reached or timed out."""


class ProviderAuthenticationError(AIStudioError):
    """The provider rejected the configured credentials."""


class ProviderRateLimitError(AIStudioError):
    """The provider rejected the request due to rate or quota limits."""


class ProviderResponseError(AIStudioError):
    """The provider returned an invalid or unsuccessful response."""


class AssetError(AIStudioError):
    """A stock asset could not be located or downloaded safely."""


class VideoRenderError(AIStudioError):
    """MoviePy or FFmpeg could not produce the requested video."""
