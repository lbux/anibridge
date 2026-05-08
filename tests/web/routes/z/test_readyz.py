"""Tests for readiness probe routes."""

from types import SimpleNamespace

import pytest
from litestar.app import Litestar
from litestar.testing.client.sync_client import TestClient

from anibridge.app.web.routes.z import readyz as readyz_module


class _DummyScheduler:
    def __init__(self, *, running: bool = False) -> None:
        self._running = running
        self.bridge_clients: dict[str, object] = {}
        self.failed_profile_errors: dict[str, str] = {}
        self.global_config = SimpleNamespace(profiles={})

    @property
    def is_running(self) -> bool:
        return self._running


@pytest.fixture
def readyz_client() -> TestClient:
    app = Litestar(route_handlers=[readyz_module.router])
    return TestClient(app)


def test_readyz_reports_scheduler_failures(
    monkeypatch: pytest.MonkeyPatch,
    readyz_client: TestClient,
) -> None:
    scheduler = _DummyScheduler(running=True)
    scheduler.global_config = SimpleNamespace(
        profiles={"one": object(), "two": object()}
    )
    scheduler.bridge_clients = {"one": object()}
    scheduler.failed_profile_errors = {"two": "Provider auth failed"}
    monkeypatch.setattr(
        readyz_module,
        "get_app_state",
        lambda: SimpleNamespace(scheduler=scheduler),
    )

    ready = readyz_client.get("/readyz")

    assert ready.status_code == 503
    assert ready.json() == {
        "status": "degraded",
        "ready": False,
        "scheduler_running": True,
        "profiles": {
            "configured": 2,
            "initialized": 1,
            "failed": 1,
        },
    }


def test_readyz_is_unavailable_without_scheduler(
    monkeypatch: pytest.MonkeyPatch,
    readyz_client: TestClient,
) -> None:
    monkeypatch.setattr(
        readyz_module,
        "get_app_state",
        lambda: SimpleNamespace(scheduler=None),
    )

    ready = readyz_client.get("/readyz")

    assert ready.status_code == 503
    assert ready.json() == {
        "status": "unavailable",
        "ready": False,
        "scheduler_running": False,
        "profiles": {
            "configured": 0,
            "initialized": 0,
            "failed": 0,
        },
    }


def test_readyz_is_ok_when_scheduler_is_running(
    monkeypatch: pytest.MonkeyPatch,
    readyz_client: TestClient,
) -> None:
    scheduler = _DummyScheduler(running=True)
    scheduler.global_config = SimpleNamespace(profiles={"one": object()})
    scheduler.bridge_clients = {"one": object()}
    monkeypatch.setattr(
        readyz_module,
        "get_app_state",
        lambda: SimpleNamespace(scheduler=scheduler),
    )

    ready = readyz_client.get("/readyz")

    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ok",
        "ready": True,
        "scheduler_running": True,
        "profiles": {
            "configured": 1,
            "initialized": 1,
            "failed": 0,
        },
    }
