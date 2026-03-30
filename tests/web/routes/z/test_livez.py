"""Tests for liveness probe routes."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from anibridge.app.web.routes.z import livez as livez_module


def test_livez_route_serves_livez_and_healthz_aliases() -> None:
    app = FastAPI()
    app.include_router(livez_module.router)
    client = TestClient(app)

    livez_response = client.get("/livez")
    healthz_response = client.get("/healthz")

    assert livez_response.status_code == 200
    assert livez_response.json() == {"status": "ok"}
    assert healthz_response.status_code == 200
    assert healthz_response.json() == {"status": "ok"}
