"""Tests for database configuration helpers."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from anibridge.app.config import database as database_module
from anibridge.app.config.database import AnibridgeDb, db
from anibridge.app.exceptions import DataPathError


@pytest.fixture
def no_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip migration execution when a test only exercises session setup."""
    monkeypatch.setattr(AnibridgeDb, "_do_migrations", lambda self: None)


def test_anibridge_db_rejects_file_data_path(
    tmp_path: Path,
    no_migrations: None,
) -> None:
    """A file data path should raise the domain-specific error."""
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("boom", encoding="utf-8")

    with pytest.raises(DataPathError, match="is a file"):
        AnibridgeDb(file_path)


def test_anibridge_db_session_property_lazily_creates_session(
    tmp_path: Path,
    no_migrations: None,
) -> None:
    """The session property should create a session outside the context manager."""
    db_client = AnibridgeDb(tmp_path / "data")
    try:
        session = db_client.session
        assert session is not None
    finally:
        db_client.close()


def test_anibridge_db_nested_contexts_keep_distinct_sessions(
    tmp_path: Path,
    no_migrations: None,
) -> None:
    """Nested contexts should not stomp each other's active sessions."""
    db_client = AnibridgeDb(tmp_path / "data")
    try:
        with db_client as outer:
            outer_session = outer.session
            with db_client as inner:
                inner_session = inner.session
                assert inner_session is not outer_session

            assert outer.session is outer_session
            assert outer_session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        db_client.close()


def test_db_cached_factory_uses_configured_data_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_migrations: None,
) -> None:
    """The cached db factory should honor the configured data path."""
    monkeypatch.setattr(
        database_module,
        "get_config",
        lambda: SimpleNamespace(data_path=tmp_path),
    )
    db.cache_clear()
    instance: AnibridgeDb | None = None
    try:
        instance = db()
        assert instance.data_path == tmp_path
    finally:
        if instance is not None:
            instance.close()
        db.cache_clear()
