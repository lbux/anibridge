"""Lightweight tests for mappings query specs (v3)."""

from anibridge.app.config.database import db
from anibridge.app.models.db.animap import AnimapEntry, AnimapMapping, AnimapProvenance
from anibridge.app.web.services.mappings_query_spec import (
    get_query_field_map,
    get_query_field_specs,
)


def _clear_tables() -> None:
    with db() as ctx:
        ctx.session.query(AnimapProvenance).delete()
        ctx.session.query(AnimapMapping).delete()
        ctx.session.query(AnimapEntry).delete()
        ctx.session.commit()


def test_query_field_map_contains_core_fields() -> None:
    """The mappings query field map contains core fields."""
    field_map = get_query_field_map()
    core_keys = {"source.provider", "source.id", "source.scope"}
    assert core_keys.issubset(set(field_map.keys()))
    assert field_map["source.provider"].desc == "Source provider"


def test_query_field_specs_include_distinct_provider_values() -> None:
    """Provider field specs include sorted values from the database."""
    _clear_tables()
    try:
        with db() as ctx:
            ctx.session.add_all(
                [
                    AnimapEntry(provider="tmdb", entry_id="10", entry_scope=None),
                    AnimapEntry(provider="anilist", entry_id="1", entry_scope=None),
                    AnimapEntry(provider="tmdb", entry_id="11", entry_scope="s1"),
                ]
            )
            ctx.session.commit()

        field_map = {spec.key: spec for spec in get_query_field_specs()}
        assert list(field_map["source.provider"].values or []) == [
            "anilist",
            "tmdb",
        ]
        assert list(field_map["target.provider"].values or []) == [
            "anilist",
            "tmdb",
        ]
    finally:
        _clear_tables()
