"""Tests for mappings API routes."""

from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from anibridge.app.config.database import db
from anibridge.app.models.db.animap import AnimapEntry, AnimapMapping, AnimapProvenance
from anibridge.app.web.routes.api import mappings as mappings_api_module


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(mappings_api_module.router, prefix="/api/mappings")
    return app


@contextmanager
def _fresh_tables():
    with db() as ctx:
        ctx.session.query(AnimapProvenance).delete()
        ctx.session.query(AnimapMapping).delete()
        ctx.session.query(AnimapEntry).delete()
        ctx.session.commit()
    try:
        yield
    finally:
        with db() as ctx:
            ctx.session.query(AnimapProvenance).delete()
            ctx.session.query(AnimapMapping).delete()
            ctx.session.query(AnimapEntry).delete()
            ctx.session.commit()


def test_query_capabilities_include_distinct_provider_values() -> None:
    """Provider query fields expose provider suggestions from the database."""
    with _fresh_tables():
        with db() as ctx:
            ctx.session.add_all(
                [
                    AnimapEntry(provider="tmdb", entry_id="10", entry_scope=None),
                    AnimapEntry(provider="anilist", entry_id="1", entry_scope=None),
                    AnimapEntry(provider="tmdb", entry_id="11", entry_scope="s1"),
                ]
            )
            ctx.session.commit()

        client = TestClient(_build_app())
        response = client.get("/api/mappings/query-capabilities")

    assert response.status_code == 200
    fields = response.json()["fields"]
    source_provider = next(
        field for field in fields if field["key"] == "source.provider"
    )
    target_provider = next(
        field for field in fields if field["key"] == "target.provider"
    )

    assert source_provider["values"] == ["anilist", "tmdb"]
    assert target_provider["values"] == ["anilist", "tmdb"]
