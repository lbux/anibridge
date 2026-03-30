"""Tests for the SQLAlchemy base model helpers."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Mapped, mapped_column

from anibridge.app.exceptions import UnsupportedModeError
from anibridge.app.models.db.base import Base


class DummyModel(Base):
    """Concrete model used to exercise the shared dump helpers."""

    __tablename__ = "dummy_model"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None]


def test_model_dump_python_mode_uses_public_attributes() -> None:
    """Default dumps should include public attributes and preserve Python objects."""
    item = DummyModel(id=1, name=None)
    item.__dict__["created_at"] = datetime(2026, 1, 1, tzinfo=UTC)
    item.__dict__["_internal"] = "hidden"

    assert item.model_dump() == {
        "id": 1,
        "name": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }


def test_model_dump_respects_include_exclude_and_exclude_none() -> None:
    """Dump filters should match the pydantic-style API contract."""
    item = DummyModel(id=1, name=None)
    item.__dict__["slug"] = "example"

    assert item.model_dump(include={"id", "name"}) == {"id": 1, "name": None}
    assert item.model_dump(exclude={"name"}) == {"id": 1, "slug": "example"}
    assert item.model_dump(exclude_none=True) == {"id": 1, "slug": "example"}


def test_model_dump_json_serializes_datetimes_and_unknown_objects() -> None:
    """JSON dumps should serialize datetimes and arbitrary values safely."""
    item = DummyModel(id=1, name="AniBridge")
    item.__dict__["created_at"] = datetime(2026, 1, 1, tzinfo=UTC)
    item.__dict__["marker"] = object()

    dumped = item.model_dump(mode="json")

    assert dumped["created_at"] == "2026-01-01T00:00:00+00:00"
    assert isinstance(dumped["marker"], str)


def test_model_dump_rejects_unknown_modes() -> None:
    """Unsupported dump modes should raise the domain-specific error."""
    with pytest.raises(UnsupportedModeError, match="Unsupported mode"):
        DummyModel(id=1, name="AniBridge").model_dump(mode="xml")
