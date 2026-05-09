"""Unit tests for the pin management service."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest

from anibridge.app.config.database import db
from anibridge.app.config.settings import SyncField
from anibridge.app.core.sched import SchedulerClient
from anibridge.app.models.db.pin import Pin
from anibridge.app.web.services.pin_service import PinService
from anibridge.app.web.state import get_app_state


class DummyListProvider:
    """Minimal list provider stub for pin service tests."""

    NAMESPACE = "anilist"

    async def get_entries_batch(self, keys):
        return [
            None,
            SimpleNamespace(
                media=lambda: SimpleNamespace(
                    key="abc",
                    title="AniBridge",
                    poster_image="https://example.test/poster.jpg",
                    external_url="https://example.test/item",
                    labels=("dub", "favorite"),
                )
            ),
        ]


@pytest.fixture(autouse=True)
def _pin_scheduler():
    """Attach a scheduler with a list provider for pin service tests."""
    state = get_app_state()
    original = state.scheduler
    bridge = SimpleNamespace(list_provider=DummyListProvider())
    state.scheduler = cast(
        SchedulerClient, SimpleNamespace(bridge_clients={"default": bridge})
    )
    yield
    state.scheduler = original


@pytest.fixture(autouse=True)
def _clear_pins():
    """Ensure the pin table is empty before and after each test."""
    with db() as ctx:
        ctx.session.query(Pin).delete()
        ctx.session.commit()
    yield
    with db() as ctx:
        ctx.session.query(Pin).delete()
        ctx.session.commit()


def _insert_pin(**overrides) -> Pin:
    now = datetime.now(UTC) - timedelta(days=1)
    pin = Pin(
        profile_name=overrides.get("profile_name", "default"),
        list_namespace=overrides.get("list_namespace", "anilist"),
        list_media_key=overrides.get("list_media_key", "abc"),
        fields=overrides.get("fields", [SyncField.STATUS.value]),
        created_at=overrides.get("created_at", now),
        updated_at=overrides.get("updated_at", now),
    )
    with db() as ctx:
        ctx.session.add(pin)
        ctx.session.commit()
        ctx.session.refresh(pin)
    return pin


@pytest.mark.asyncio
async def test_pin_service_upsert_normalizes_and_validates_fields():
    """Upserts should normalize field order, dedupe entries, and reject invalid
    fields.
    """
    service = PinService()

    created = await service.upsert_pin(
        "default",
        "abc",
        [
            SyncField.STATUS,
            " progress ",
            SyncField.STATUS,
            "USER_RATING",
        ],
    )
    assert created.fields == [
        SyncField.STATUS.value,
        SyncField.PROGRESS.value,
        SyncField.USER_RATING.value,
    ]

    with pytest.raises(ValueError, match="Unsupported field"):
        await service.upsert_pin("default", "missing", ["missing"])

    spaced = await service.upsert_pin("default", "spaced", [" ", "status"])
    assert spaced.fields == [SyncField.STATUS.value]


def test_pin_service_lists_available_field_options():
    """Selectable pin options should expose user-facing labels."""
    options = PinService().list_options()

    assert options[0].value == SyncField.STATUS.value
    assert options[0].label == "Status"


@pytest.mark.asyncio
async def test_pin_service_lists_and_serializes_entries():
    """Return entries ordered by most recent update and serialize fields."""
    service = PinService()
    _insert_pin(list_media_key="1", fields=[SyncField.STATUS.value])
    newer = _insert_pin(
        list_media_key="2",
        fields=[SyncField.USER_RATING.value],
        updated_at=datetime.now(UTC),
    )

    pins = await service.list_pins("default")
    assert [pin.list_media_key for pin in pins] == ["2", "1"]
    assert pins[0].fields == [SyncField.USER_RATING.value]

    fetched = await service.get_pin("default", newer.list_media_key)
    assert fetched is not None
    assert fetched.fields == newer.fields


@pytest.mark.asyncio
async def test_pin_service_upsert_and_delete_roundtrip():
    """Upsert pins, refresh timestamps, and delete entries cleanly."""
    service = PinService()

    created = await service.upsert_pin(
        "default",
        "abc",
        [SyncField.PROGRESS.value, SyncField.STATUS.value],
    )
    assert sorted(created.fields) == [SyncField.PROGRESS.value, SyncField.STATUS.value]

    updated = await service.upsert_pin(
        "default",
        "abc",
        [SyncField.REPEATS.value],
    )
    assert updated.fields == [SyncField.REPEATS.value]
    assert updated.updated_at >= created.updated_at

    service.delete_pin("default", "abc")
    assert await service.get_pin("default", "abc") is None

    with pytest.raises(ValueError):
        await service.upsert_pin("default", "xyz", [])


@pytest.mark.asyncio
async def test_pin_service_enriches_entries_with_media_metadata():
    """with_media should merge provider metadata into pin responses."""
    service = PinService()
    _insert_pin(list_media_key="abc", fields=[SyncField.STATUS.value])

    listed = await service.list_pins("default", with_media=True)
    fetched = await service.get_pin("default", "abc", with_media=True)
    updated = await service.upsert_pin(
        "default",
        "abc",
        [SyncField.STATUS.value],
        with_media=True,
    )

    assert listed[0].media is not None
    assert listed[0].media.title == "AniBridge"
    assert listed[0].media.labels == ["dub", "favorite"]
    assert fetched is not None and fetched.media is not None
    assert updated.media is not None


def test_pin_service_delete_missing_pin_is_noop():
    """Deleting a missing pin should quietly return."""
    PinService().delete_pin("default", "missing")
