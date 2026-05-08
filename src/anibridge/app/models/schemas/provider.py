"""Generic provider metadata schemas used across the web API."""

import msgspec

__all__ = ["ProviderMediaMetadata"]


class ProviderMediaMetadata(msgspec.Struct):
    """Provider-agnostic description of a media item."""

    namespace: str
    key: str
    title: str | None = None
    poster_url: str | None = None
    external_url: str | None = None
    labels: list[str] | None = None
