"""Unit tests for sync history persistence helpers."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from anibridge.library import MediaKind
from anibridge.list import ListStatus
from anibridge.utils.mappings import AnibridgeDescriptorMapping
from sqlalchemy.engine import create_engine
from sqlalchemy.orm import sessionmaker

from anibridge.app.core.sync.history import SyncHistoryManager
from anibridge.app.core.sync.stats import EntrySnapshot
from anibridge.app.models.db.animap import AnimapEntry
from anibridge.app.models.db.base import Base
from anibridge.app.models.db.sync_history import SyncHistory, SyncOutcome


@pytest.fixture
def history_db_factory():
    """Provide an in-memory db factory for history manager tests."""
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
def history_manager(history_db_factory) -> SyncHistoryManager:
    """Create a sync history manager bound to the in-memory db."""
    return SyncHistoryManager(
        profile_name="profile",
        library_namespace="plex",
        list_namespace="anilist",
        db_factory=history_db_factory,
    )


class FakeItem:
    def __init__(self, key: str, media_key: str | None = None):
        self.key = key
        self.title = key
        self._media_key = media_key or key
        self.media_kind = MediaKind.MOVIE
        self._section = SimpleNamespace(key="section-1", title="Section 1")

    def section(self):
        return self._section

    def media(self):
        return SimpleNamespace(key=self._media_key)

    def mapping_descriptors(self):
        return []


def _item(key: str = "lib1", media_key: str | None = None) -> Any:

    return FakeItem(key, media_key=media_key)


@pytest.mark.asyncio
async def test_create_sync_history_skips_skipped_rows(
    history_manager: SyncHistoryManager,
    history_db_factory,
) -> None:
    """Skipped outcomes should not persist rows."""
    await history_manager.create_sync_history(
        item=_item(),
        child_item=None,
        grandchild_items=None,
        snapshots=(None, None),
        list_media_key=None,
        outcome=SyncOutcome.SKIPPED,
    )

    with history_db_factory() as ctx:
        assert ctx.session.query(SyncHistory).count() == 0


@pytest.mark.asyncio
async def test_create_sync_history_updates_existing_failure_record(
    history_manager: SyncHistoryManager,
    history_db_factory,
) -> None:
    """Repeated failure rows should update, not duplicate, the stored failure."""
    with history_db_factory() as ctx:
        ctx.session.add(
            SyncHistory(
                profile_name="profile",
                library_namespace="plex",
                library_section_key="section-1",
                library_media_key="lib1",
                list_namespace="anilist",
                list_media_key="lst1",
                media_kind=MediaKind.MOVIE,
                outcome=SyncOutcome.FAILED,
                before_state=None,
                after_state=None,
                info={"outcome": "failed"},
                error_message="old",
            )
        )
        ctx.session.commit()

    before = EntrySnapshot(
        media_key="lst1",
        status=ListStatus.PLANNING,
        progress=None,
        repeats=None,
        review=None,
        user_rating=None,
        started_at=None,
        finished_at=None,
    )
    after = EntrySnapshot(
        media_key="lst1",
        status=ListStatus.CURRENT,
        progress=1,
        repeats=None,
        review=None,
        user_rating=None,
        started_at=None,
        finished_at=None,
    )

    await history_manager.create_sync_history(
        item=_item(),
        child_item=None,
        grandchild_items=None,
        snapshots=(before, after),
        list_media_key="lst1",
        outcome=SyncOutcome.FAILED,
        error_message="new",
        info={"source": "retry"},
    )

    with history_db_factory() as ctx:
        rows = ctx.session.query(SyncHistory).all()
        assert len(rows) == 1
        assert rows[0].error_message == "new"
        assert rows[0].info["source"] == "retry"


@pytest.mark.asyncio
async def test_create_sync_history_persists_library_entry_key(
    history_manager: SyncHistoryManager,
    history_db_factory,
) -> None:
    """History rows should persist the provider entry key, not the media key."""
    await history_manager.create_sync_history(
        item=_item(key="rating-key", media_key="guid://media-key"),
        child_item=None,
        grandchild_items=None,
        snapshots=(None, None),
        list_media_key=None,
        outcome=SyncOutcome.NOT_FOUND,
    )

    with history_db_factory() as ctx:
        rows = ctx.session.query(SyncHistory).all()
        assert len(rows) == 1
        assert rows[0].library_media_key == "rating-key"
        assert rows[0].info is not None
        assert rows[0].info.get("library_section") == "Section 1 (section-1)"
        assert rows[0].info.get("library_item") == "rating-key (rating-key)"
        assert "list_media_key" not in rows[0].info
        assert "mapping_sources" not in rows[0].info


@pytest.mark.asyncio
async def test_create_sync_history_persists_child_context(
    history_manager: SyncHistoryManager,
    history_db_factory,
) -> None:
    """History rows should include child identifiers when they add context."""

    class _ChildItem(FakeItem):
        def __init__(self):
            super().__init__("season-2")
            self.title = "Season 2"

    parent = _item(key="show-1")
    parent.title = "Show"

    await history_manager.create_sync_history(
        item=parent,
        child_item=cast(Any, _ChildItem()),
        grandchild_items=cast(
            Any,
            [SimpleNamespace(key="ep-1"), SimpleNamespace(key="ep-2")],
        ),
        snapshots=(None, None),
        list_media_key="lst1",
        outcome=SyncOutcome.SYNCED,
    )

    with history_db_factory() as ctx:
        row = ctx.session.query(SyncHistory).one()
        assert row.info is not None
        assert row.info.get("library_item") == "Show (show-1)"
        assert row.info.get("library_child_item") == "Season 2 (season-2)"
        assert row.info.get("library_grandchild_items") == "2"


@pytest.mark.asyncio
async def test_create_sync_history_persists_mapping_target(
    history_manager: SyncHistoryManager,
    history_db_factory,
) -> None:
    """History rows should include the resolved mapping target descriptor."""
    await history_manager.create_sync_history(
        item=_item(),
        child_item=None,
        grandchild_items=None,
        snapshots=(None, None),
        list_media_key="lst1",
        mappings=[
            AnibridgeDescriptorMapping(
                source=("anilist", "101", None),
                target=("tmdb", "201", "movie"),
            )
        ],
        outcome=SyncOutcome.SYNCED,
    )

    with history_db_factory() as ctx:
        row = ctx.session.query(SyncHistory).one()
        assert row.info is not None
        assert row.info.get("mapping_targets") == "tmdb:201:movie"


@pytest.mark.asyncio
async def test_create_sync_history_persists_mapping_sources(
    history_manager: SyncHistoryManager,
    history_db_factory,
) -> None:
    """History rows should include the resolved mapping sources used for sync."""
    mapping = AnibridgeDescriptorMapping(
        source=("anilist", "101", None),
        target=("tmdb", "201", "movie"),
    )
    mapping.add_mapping("2", "5")
    mapping.add_mapping("3-4", "7-8")

    await history_manager.create_sync_history(
        item=_item(),
        child_item=None,
        grandchild_items=None,
        snapshots=(None, None),
        list_media_key="lst1",
        mappings=[mapping],
        outcome=SyncOutcome.SYNCED,
    )

    with history_db_factory() as ctx:
        row = ctx.session.query(SyncHistory).one()
        assert row.info is not None
        assert row.info.get("mapping_sources") == "anilist:101"


def test_queue_cleanup_flushes_threshold_and_resolves_mapping_entry_id(
    history_manager: SyncHistoryManager,
    history_db_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup queueing should flush at threshold and mapping ids should resolve."""
    flushed: list[bool] = []
    monkeypatch.setattr(
        history_manager, "flush_failure_history_cleanup", lambda: flushed.append(True)
    )

    history_manager.queue_failure_history_cleanup(item=_item(), list_media_key="lst1")
    assert flushed == []

    history_manager._failure_history_cleanup_queue = {
        ("section-1", str(index), None) for index in range(255)
    }
    history_manager.queue_failure_history_cleanup(
        item=_item(key="lib256"), list_media_key=None
    )
    assert flushed == [True]

    with history_db_factory() as ctx:
        entry = AnimapEntry(provider="anilist", entry_id="101", entry_scope=None)
        ctx.session.add(entry)
        ctx.session.commit()
        mapping_id = history_manager._get_mapping_entry_id(
            mappings=[
                AnibridgeDescriptorMapping(
                    source=("anilist", "101", None),
                    target=("tmdb", "201", None),
                )
            ],
            session=ctx.session,
        )
        assert mapping_id == entry.id
        assert (
            history_manager._get_mapping_entry_id(mappings=None, session=ctx.session)
            is None
        )


def test_update_existing_failure_record_handles_misses_and_identical_rows(
    history_manager: SyncHistoryManager,
    history_db_factory,
) -> None:
    """Failure update helper should distinguish missing, identical, and changed rows."""
    with history_db_factory() as ctx:
        assert (
            history_manager._update_existing_failure_record(
                session=ctx.session,
                library_section_key="section-1",
                library_media_key="lib1",
                list_media_key=None,
                outcome=SyncOutcome.FAILED,
                before_state=None,
                after_state=None,
                history_info={"outcome": "failed"},
                error_message="boom",
                mapping_entry_info=None,
            )
            is False
        )

        row = SyncHistory(
            profile_name="profile",
            library_namespace="plex",
            library_section_key="section-1",
            library_media_key="lib1",
            list_namespace="anilist",
            list_media_key=None,
            media_kind=MediaKind.MOVIE,
            outcome=SyncOutcome.FAILED,
            before_state=None,
            after_state=None,
            info={"outcome": "failed"},
            error_message="boom",
        )
        ctx.session.add(row)
        ctx.session.commit()

        assert (
            history_manager._update_existing_failure_record(
                session=ctx.session,
                library_section_key="section-1",
                library_media_key="lib1",
                list_media_key=None,
                outcome=SyncOutcome.FAILED,
                before_state=None,
                after_state=None,
                history_info={"outcome": "failed"},
                error_message="boom",
                mapping_entry_info=None,
            )
            is True
        )
