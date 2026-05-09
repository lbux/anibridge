"""Generic provider metadata schemas used across the web API."""

from typing import Annotated

import msgspec

__all__ = ["ProviderMediaMetadata"]


class ProviderMediaMetadata(msgspec.Struct):
    """Provider-agnostic description of a media item."""

    namespace: Annotated[
        str,
        msgspec.Meta(
            min_length=1,
            description="Provider namespace for the media item.",
            examples=["anilist"],
        ),
    ]
    key: Annotated[
        str,
        msgspec.Meta(
            min_length=1,
            description="Provider-specific stable key for the media item.",
            examples=["12345"],
        ),
    ]
    title: (
        Annotated[
            str,
            msgspec.Meta(
                description="Display title of the media item.",
                examples=["Fullmetal Alchemist: Brotherhood"],
            ),
        ]
        | None
    ) = None
    poster_url: (
        Annotated[
            str,
            msgspec.Meta(
                description="Poster or cover image URL for the media item.",
                examples=["https://cdn.example.com/posters/fmab.jpg"],
            ),
        ]
        | None
    ) = None
    external_url: (
        Annotated[
            str,
            msgspec.Meta(
                description="External provider URL for the media item.",
                examples=["https://anilist.co/anime/5114"],
            ),
        ]
        | None
    ) = None
    labels: (
        Annotated[
            list[str],
            msgspec.Meta(
                description="Supplemental provider labels associated with the item.",
                examples=[["Dubbed", "Movie"]],
            ),
        ]
        | None
    ) = None
