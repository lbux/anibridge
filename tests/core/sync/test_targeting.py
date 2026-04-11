"""Unit tests for `anibridge.app.core.sync.targeting`."""

from datetime import UTC, datetime
from typing import cast

import pytest
from anibridge.list import ListEntry as ListEntryProtocol
from anibridge.list import ListMediaType, ListStatus
from anibridge.list.base import ListProvider

from anibridge.app.core.animap import AnimapClient
from anibridge.app.core.sync.stats import EntrySnapshot
from anibridge.app.core.sync.targeting import (
    diff_snapshots,
    find_best_search_result,
    resolve_list_targets,
)
from tests.core.sync.conftest import (
    FakeAnimapClient,
    FakeLibraryMovie,
    FakeListEntry,
    FakeListProvider,
)


def test_diff_snapshots_returns_changed_fields() -> None:
    """`diff_snapshots` only includes differences for requested fields."""
    before = EntrySnapshot(
        media_key="123",
        status=ListStatus.CURRENT,
        progress=3,
        repeats=0,
        review=None,
        user_rating=50,
        started_at=datetime(2025, 1, 1, tzinfo=UTC),
        finished_at=None,
    )
    after = EntrySnapshot(
        media_key="123",
        status=ListStatus.COMPLETED,
        progress=6,
        repeats=0,
        review="Updated",
        user_rating=80,
        started_at=datetime(2025, 1, 1, tzinfo=UTC),
        finished_at=datetime(2025, 2, 1, tzinfo=UTC),
    )

    diff = diff_snapshots(before, after, {"status", "progress", "finished_at"})

    assert diff == {
        "status": (ListStatus.CURRENT, ListStatus.COMPLETED),
        "progress": (3, 6),
        "finished_at": (None, datetime(2025, 2, 1, tzinfo=UTC)),
    }


def test_best_search_result_applies_threshold() -> None:
    """Fuzzy matching respects the configured fallback threshold."""
    provider = FakeListProvider()
    exact = FakeListEntry(
        provider=provider,
        key="1",
        title="Perfect Match",
        media_type=ListMediaType.MOVIE,
    )
    off = FakeListEntry(
        provider=provider,
        key="2",
        title="Different",
        media_type=ListMediaType.MOVIE,
    )

    entries = [cast(ListEntryProtocol, exact), cast(ListEntryProtocol, off)]
    pick = find_best_search_result("Perfect Match", entries, 80)
    assert pick is exact

    assert (
        find_best_search_result("Perfect Match", [cast(ListEntryProtocol, off)], 95)
        is None
    )


@pytest.mark.asyncio
async def test_resolve_list_targets_supports_one_to_many() -> None:
    """List resolution returns multiple targets for a single descriptor."""
    provider = cast(ListProvider, FakeListProvider())
    descriptor = ("anilist", "100", None)
    provider.resolved_targets = {descriptor: ["100", "101"]}  # ty:ignore[unresolved-attribute]
    movie = FakeLibraryMovie(
        key="movie-1",
        title="Movie",
        mapping_descriptors=[descriptor],
    )

    targets = await resolve_list_targets(
        animap_client=cast(AnimapClient, FakeAnimapClient()),
        list_provider=provider,
        media_items=(movie,),
    )
    keys = {target.list_media_key for target in targets}

    assert keys == {"100", "101"}


@pytest.mark.asyncio
async def test_resolve_list_targets_skips_stub_only_mapping_ranges() -> None:
    """Stubbed (zero-ratio) mapping segments should not produce sync targets."""

    class StubAnimapClient(FakeAnimapClient):
        def resolve_edges_grouped(self, descriptors, *, target_providers=None):
            return {
                ("anilist", "31", None): {
                    ("plex", "eoe", None): [("1", "1|0")],
                }
            }

    provider = cast(ListProvider, FakeListProvider())
    provider.resolved_targets = {("anilist", "31", None): ["31"]}  # ty:ignore[unresolved-attribute]
    movie = FakeLibraryMovie(
        key="movie-1",
        title="End of Evangelion",
        mapping_descriptors=[("plex", "eoe", None)],
    )

    targets = await resolve_list_targets(
        animap_client=cast(AnimapClient, StubAnimapClient()),
        list_provider=provider,
        media_items=(movie,),
    )

    assert targets == ()
