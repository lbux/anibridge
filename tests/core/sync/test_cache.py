"""Unit tests for sync cache helpers."""

from pathlib import Path
from typing import Any, cast

import pytest
from anibridge.list import ListEntry, ListMediaType, ListProvider, ListStatus
from sqlalchemy.engine import create_engine
from sqlalchemy.orm import sessionmaker

from anibridge.app.core.sync.cache import SyncCacheManager
from anibridge.app.models.db.base import Base
from anibridge.app.models.db.pin import Pin
from tests.core.sync.conftest import FakeListEntry, FakeListProvider


@pytest.fixture
def pin_db_factory(tmp_path: Path):
    """Provide a lightweight SQLite-backed db factory for pin lookups."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True, autoflush=False)

    class _DB:
        def __init__(self) -> None:
            self._session = None

        def __enter__(self):
            self._session = session_factory()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb) -> None:
            if self._session is not None:
                self._session.close()
                self._session = None

        @property
        def session(self):
            if self._session is None:
                self._session = session_factory()
            return self._session

    def _factory():
        return _DB()

    yield _factory
    engine.dispose()


@pytest.fixture
def cache_manager(pin_db_factory) -> SyncCacheManager:
    """Create the cache manager under test with a fake provider."""
    provider = cast(ListProvider, FakeListProvider())
    return SyncCacheManager(
        list_provider=provider,
        profile_name="profile",
        db_factory=pin_db_factory,
    )


def _make_entry(
    provider: FakeListProvider,
    *,
    key: str,
    title: str = "Item",
) -> FakeListEntry:
    return FakeListEntry(
        provider=provider,
        key=key,
        title=title,
        media_type=ListMediaType.MOVIE,
    )


def test_clear_cache_and_apply_planned_update(cache_manager: SyncCacheManager) -> None:
    """Cache clearing and in-memory planned updates should mutate cached entries."""
    provider = cast(FakeListProvider, cache_manager.list_provider)
    source = _make_entry(provider, key="1")
    planned = _make_entry(provider, key="1")
    planned.status = ListStatus.COMPLETED

    cache_manager.cache_entry(cast(ListEntry[Any], source))
    cache_manager._pin_cache[("alist", "1")] = ["status"]
    SyncCacheManager.apply_planned_update(
        source_entry=cast(ListEntry[Any], source),
        planned_entry=cast(ListEntry[Any], planned),
        fields=["status"],
    )
    SyncCacheManager.apply_planned_update(
        source_entry=None,
        planned_entry=cast(ListEntry[Any], planned),
        fields=["status"],
    )

    assert source.status == ListStatus.COMPLETED
    cache_manager.clear_cache()
    assert cache_manager._prefetched_entries == {}
    assert cache_manager._pin_cache == {}


@pytest.mark.asyncio
async def test_get_entry_prefers_cache_and_caches_provider_fetch(
    cache_manager: SyncCacheManager,
) -> None:
    """get_entry should return cached values and memoize provider fetches."""
    provider = cast(FakeListProvider, cache_manager.list_provider)
    entry = _make_entry(provider, key="7")
    provider.entries["7"] = entry

    first = await cache_manager.get_entry("7")
    provider.entries["7"] = _make_entry(provider, key="7", title="Updated")
    second = await cache_manager.get_entry("7")

    assert first is entry
    assert second is entry


@pytest.mark.asyncio
async def test_prefetch_entries_handles_partial_failures_and_empty_batches(
    cache_manager: SyncCacheManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prefetching should skip failed key collection and ignore empty keys."""
    provider = cast(FakeListProvider, cache_manager.list_provider)
    provider.entries["2"] = _make_entry(provider, key="2")

    async def _get_entries_batch(keys: tuple[str, ...]):
        return [provider.entries[key] for key in keys]

    monkeypatch.setattr(
        provider,
        "get_entries_batch",
        _get_entries_batch,
        raising=False,
    )

    async def _collect_keys(item: str) -> tuple[str, ...]:
        if item == "bad":
            raise RuntimeError("boom")
        if item == "empty":
            return ()
        return ("2",)

    await cache_manager.prefetch_entries(
        items=["bad", "empty", "good"], collect_keys=_collect_keys
    )

    assert await cache_manager.get_entry("2") is provider.entries["2"]


@pytest.mark.asyncio
async def test_prefetch_entries_handles_batch_errors(
    cache_manager: SyncCacheManager,
) -> None:
    """Batch fetch failures should not populate the local cache."""
    provider = cast(FakeListProvider, cache_manager.list_provider)

    async def _get_entries_batch(_keys: tuple[str, ...]):
        raise RuntimeError("boom")

    async def _collect_keys(_item: str) -> tuple[str, ...]:
        return ("missing",)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        provider,
        "get_entries_batch",
        _get_entries_batch,
        raising=False,
    )
    await cache_manager.prefetch_entries(items=["x"], collect_keys=_collect_keys)
    monkeypatch.undo()

    assert await cache_manager.get_entry("missing") is None


def test_get_pinned_fields_uses_cache_and_handles_missing_media_key(
    cache_manager: SyncCacheManager,
    pin_db_factory,
) -> None:
    """Pinned field lookups should short-circuit on missing keys and cache results."""
    assert cache_manager.get_pinned_fields("alist", None) == []

    with pin_db_factory() as ctx:
        ctx.session.add(
            Pin(
                profile_name="profile",
                list_namespace="alist",
                list_media_key="123",
                fields=["status", "progress"],
            )
        )
        ctx.session.commit()

    first = cache_manager.get_pinned_fields("alist", "123")
    second = cache_manager.get_pinned_fields("alist", "123")

    assert first == ["status", "progress"]
    assert second == ["status", "progress"]
