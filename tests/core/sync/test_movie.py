"""Unit tests for `anibridge.app.core.sync.movie` field calculations."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import pytest
from anibridge.library import LibraryMovie as LibraryMovieProtocol
from anibridge.library import LibraryProvider
from anibridge.list import ListEntry as ListEntryProtocol
from anibridge.list import ListMediaType, ListProvider, ListStatus

from anibridge.app.core.sync.movie import MovieSyncClient
from anibridge.app.models.db.sync_history import SyncHistory
from tests.core.sync.conftest import (
    FakeAnimapClient,
    FakeLibraryMovie,
    FakeLibraryProvider,
    FakeListEntry,
    FakeListProvider,
    make_history_entry,
)

if TYPE_CHECKING:
    from anibridge.app.config.database import AnibridgeDb


@pytest.fixture
def movie_client() -> MovieSyncClient:
    """Provide a configured movie sync client."""
    return MovieSyncClient(
        library_provider=cast(LibraryProvider, FakeLibraryProvider()),
        list_provider=cast(ListProvider, FakeListProvider()),
        animap_client=cast(Any, FakeAnimapClient()),
        full_scan=False,
        destructive_sync=False,
        search_fallback_threshold=75,
        batch_requests=False,
        dry_run=False,
        profile_name="tester",
    )


def make_movie(**kwargs) -> FakeLibraryMovie:
    """Helper for constructing fake movies with sensible defaults."""
    return FakeLibraryMovie(key="movie-1", title="Movie", **kwargs)


def _call_args(
    movie: FakeLibraryMovie,
    entry: FakeListEntry,
) -> dict[str, Any]:
    """Cast fake objects to their runtime protocols for private hooks."""
    library_movie = cast(LibraryMovieProtocol, movie)
    return {
        "item": library_movie,
        "child_item": library_movie,
        "grandchild_items": cast(Sequence[LibraryMovieProtocol], (library_movie,)),
        "entry": cast(ListEntryProtocol, entry),
    }


@pytest.mark.asyncio
async def test_calculate_status_based_on_watch_flags(
    movie_client: MovieSyncClient,
) -> None:
    """Status derives from view counts, watchlist flags, and playback state."""
    entry = FakeListEntry(
        provider=FakeListProvider(),
        key="1",
        title="Movie",
        media_type=ListMediaType.MOVIE,
    )
    watched = make_movie(view_count=2, on_watching=True)
    status = await movie_client._calculate_status(**_call_args(watched, entry))
    assert status == ListStatus.REPEATING

    finished = make_movie(view_count=1, on_watchlist=False, on_watching=False)
    status = await movie_client._calculate_status(**_call_args(finished, entry))
    assert status == ListStatus.COMPLETED

    planning = make_movie(view_count=0, on_watchlist=True)
    status = await movie_client._calculate_status(**_call_args(planning, entry))
    assert status == ListStatus.PLANNING

    idle = make_movie(view_count=0, on_watchlist=False)
    status = await movie_client._calculate_status(**_call_args(idle, entry))
    assert status is None


@pytest.mark.asyncio
async def test_calculate_status_empty_sync_marks_idle_as_planning(
    movie_client: MovieSyncClient,
) -> None:
    """empty_sync should classify idle movies as planning."""
    movie_client.empty_sync = True
    entry = FakeListEntry(
        provider=FakeListProvider(),
        key="1",
        title="Movie",
        media_type=ListMediaType.MOVIE,
    )
    idle = make_movie(view_count=0, on_watchlist=False, history=[])

    status = await movie_client._calculate_status(**_call_args(idle, entry))

    assert status == ListStatus.PLANNING


@pytest.mark.asyncio
async def test_calculate_status_empty_sync_skips_existing_entry(
    movie_client: MovieSyncClient,
) -> None:
    """empty_sync should not force planning for already tracked movie entries."""
    movie_client.empty_sync = True
    entry = FakeListEntry(
        provider=FakeListProvider(),
        key="1",
        title="Movie",
        media_type=ListMediaType.MOVIE,
    )
    entry.status = ListStatus.COMPLETED
    idle = make_movie(view_count=0, on_watchlist=False, history=[])

    status = await movie_client._calculate_status(**_call_args(idle, entry))

    assert status is None


@pytest.mark.asyncio
async def test_progress_and_repeats(movie_client: MovieSyncClient) -> None:
    """Progress equals total units when watched and repeats reflect extra views."""
    entry = FakeListEntry(
        provider=FakeListProvider(),
        key="1",
        title="Movie",
        media_type=ListMediaType.MOVIE,
        total_units=1,
    )
    movie = make_movie(view_count=3)

    args = _call_args(movie, entry)
    progress = await movie_client._calculate_progress(**args)
    repeats = await movie_client._calculate_repeats(**args)

    assert progress == 1
    assert repeats == 2


@pytest.mark.asyncio
async def test_started_and_finished_dates_use_history(
    movie_client: MovieSyncClient,
) -> None:
    """History timestamps drive start/finish calculations."""
    history = [
        make_history_entry("movie-1", ts=datetime(2025, 1, 5, tzinfo=UTC)),
        make_history_entry("movie-1", ts=datetime(2025, 1, 1, tzinfo=UTC)),
        make_history_entry("movie-1", ts=datetime(2025, 1, 3, tzinfo=UTC)),
    ]
    movie = make_movie(view_count=1, history=history)
    entry = FakeListEntry(
        provider=FakeListProvider(),
        key="1",
        title="Movie",
        media_type=ListMediaType.MOVIE,
    )

    args = _call_args(movie, entry)
    started = await movie_client._calculate_started_at(**args)
    finished = await movie_client._calculate_finished_at(**args)

    assert started == history[1].viewed_at
    assert finished == history[0].viewed_at


@pytest.mark.asyncio
async def test_calculate_review_prefers_movie_review(
    movie_client: MovieSyncClient,
) -> None:
    """The movie's review text is reused on the list entry."""
    entry = FakeListEntry(
        provider=FakeListProvider(),
        key="1",
        title="Movie",
        media_type=ListMediaType.MOVIE,
    )
    movie = make_movie(review="Masterpiece")

    calculated_review = await movie_client._calculate_review(**_call_args(movie, entry))
    assert calculated_review == "Masterpiece"


@pytest.mark.asyncio
async def test_resolve_mapping_targets_prefers_animap_entry(
    movie_client: MovieSyncClient,
) -> None:
    """Animap matches should resolve through the mapping phase."""
    provider = cast(FakeListProvider, movie_client.list_provider)
    entry = FakeListEntry(
        provider=provider,
        key="101",
        title="Movie",
        media_type=ListMediaType.MOVIE,
    )
    provider.entries["101"] = entry
    provider.derived_keys = ["101"]

    movie = make_movie(view_count=1, ids={"anilist": "101"})
    library_movie = cast(LibraryMovieProtocol, movie)
    results = await movie_client.resolve_mapping_targets(library_movie)

    assert len(results) == 1
    _, _, target = results[0]
    assert target.entry is entry
    assert target.list_media_key == "101"


@pytest.mark.asyncio
async def test_resolve_targets_uses_search_when_no_mapping(
    movie_client: MovieSyncClient,
) -> None:
    """Search fallback returns the best movie candidate when mapping fails."""
    provider = cast(FakeListProvider, movie_client.list_provider)
    provider.search_results = [
        FakeListEntry(
            provider=provider,
            key="201",
            title="Movie",
            media_type=ListMediaType.MOVIE,
        ),
        FakeListEntry(
            provider=provider,
            key="202",
            title="Show",
            media_type=ListMediaType.TV,
        ),
    ]
    movie_client.search_fallback_threshold = 0

    movie = make_movie()
    library_movie = cast(LibraryMovieProtocol, movie)
    results = await movie_client.resolve_targets(library_movie)

    assert len(results) == 1
    _, _, target = results[0]
    assert target.entry is provider.search_results[0]


@pytest.mark.asyncio
async def test_resolve_targets_skips_search_when_disabled(
    movie_client: MovieSyncClient,
) -> None:
    """Disabling fallback search should skip the search phase entirely."""
    provider = cast(FakeListProvider, movie_client.list_provider)
    provider.search_results = [
        FakeListEntry(
            provider=provider,
            key="301",
            title="Movie",
            media_type=ListMediaType.MOVIE,
        )
    ]
    movie_client.search_fallback_threshold = -1
    movie = make_movie()
    library_movie = cast(LibraryMovieProtocol, movie)
    assert await movie_client.resolve_targets(library_movie) == ()


@pytest.mark.asyncio
async def test_clear_cache_clears_history_cache(movie_client: MovieSyncClient) -> None:
    """clear_cache should also reset the cached movie history helper."""
    movie = make_movie(
        history=[make_history_entry("movie-1", ts=datetime(2025, 1, 1, tzinfo=UTC))]
    )
    entry = FakeListEntry(
        provider=FakeListProvider(),
        key="1",
        title="Movie",
        media_type=ListMediaType.MOVIE,
    )

    await movie_client._calculate_started_at(**_call_args(movie, entry))
    await movie_client.clear_cache()
    history = await movie_client._get_history(cast(LibraryMovieProtocol, movie))

    assert history == movie._history


@pytest.mark.asyncio
async def test_calculate_status_handles_current_and_dropped(
    movie_client: MovieSyncClient,
) -> None:
    """Current and dropped states should reflect playback flags and history."""
    entry = FakeListEntry(
        provider=FakeListProvider(),
        key="1",
        title="Movie",
        media_type=ListMediaType.MOVIE,
    )
    current = make_movie(view_count=0, on_watching=True, history=[])
    dropped = make_movie(
        view_count=0,
        on_watching=False,
        on_watchlist=False,
        history=[make_history_entry("movie-1", ts=datetime(2025, 1, 1, tzinfo=UTC))],
    )

    assert (
        await movie_client._calculate_status(**_call_args(current, entry))
        == ListStatus.CURRENT
    )
    assert (
        await movie_client._calculate_status(**_call_args(dropped, entry))
        == ListStatus.DROPPED
    )


@pytest.mark.asyncio
async def test_started_and_finished_dates_return_none_without_history(
    movie_client: MovieSyncClient,
) -> None:
    """Date calculations should return None when the movie has no history."""
    movie = make_movie(history=[])
    entry = FakeListEntry(
        provider=FakeListProvider(),
        key="1",
        title="Movie",
        media_type=ListMediaType.MOVIE,
    )

    assert await movie_client._calculate_started_at(**_call_args(movie, entry)) is None
    assert await movie_client._calculate_finished_at(**_call_args(movie, entry)) is None


@pytest.mark.asyncio
async def test_resolve_mapping_targets_returns_multiple_targets(
    movie_client: MovieSyncClient,
) -> None:
    """Mapping graphs can resolve multiple list targets for a movie."""
    provider = cast(FakeListProvider, movie_client.list_provider)
    entry_a = FakeListEntry(
        provider=provider,
        key="901",
        title="Movie",
        media_type=ListMediaType.MOVIE,
    )
    entry_b = FakeListEntry(
        provider=provider,
        key="902",
        title="Movie",
        media_type=ListMediaType.MOVIE,
    )
    provider.entries["901"] = entry_a
    provider.entries["902"] = entry_b
    provider.derived_keys = ["901", "902"]

    movie = make_movie(view_count=1, ids={"anilist": "901"})
    library_movie = cast(LibraryMovieProtocol, movie)
    results = await movie_client.resolve_mapping_targets(library_movie)

    assert len(results) == 2
    targets = {result[2].list_media_key for result in results}
    assert targets == {"901", "902"}


@pytest.mark.asyncio
async def test_process_media_syncs_movie_and_writes_history(
    movie_client: MovieSyncClient, sync_db: AnibridgeDb
) -> None:
    """Processing a movie exercises BaseSyncClient's sync pipeline."""
    provider = cast(FakeListProvider, movie_client.list_provider)
    entry = FakeListEntry(
        provider=provider,
        key="301",
        title="Movie",
        media_type=ListMediaType.MOVIE,
        total_units=1,
    )
    provider.entries["301"] = entry
    provider.derived_keys = ["301"]

    history = [make_history_entry("movie-1", ts=datetime(2025, 1, 1, tzinfo=UTC))]
    movie = make_movie(
        view_count=1,
        user_rating=90,
        history=history,
        ids={"anilist": "301"},
    )

    await movie_client.process_media(cast(LibraryMovieProtocol, movie))

    assert provider.updated_entries and provider.updated_entries[0][0] == "301"
    assert movie_client.sync_stats.synced == 1

    with sync_db as ctx:
        assert ctx.session.query(SyncHistory).count() == 1
