"""Tests for the FastAPI application factory and lifespan."""

import logging
from logging import Handler
from pathlib import Path

import pytest
from fastapi.responses import Response
from fastapi.testclient import TestClient
from starlette.requests import Request

from anibridge.app.exceptions import AnibridgeError, ProfileNotFoundError
from anibridge.app.web import app as app_module


class _DummyHandler(Handler):
    def emit(self, record) -> None:
        pass

    def set_event_loop(self, loop) -> None:
        self.loop = loop


class _DummyState:
    def __init__(self) -> None:
        self.scheduler = None
        self.scheduler_set = None
        self.shutdown_called = False
        self.ensure_calls = 0

    def set_scheduler(self, scheduler) -> None:
        self.scheduler_set = scheduler
        self.scheduler = scheduler

    async def ensure_public_anilist(self) -> None:
        self.ensure_calls += 1

    async def shutdown(self) -> None:
        self.shutdown_called = True


class _DummyScheduler:
    def __init__(self, *, running: bool = False) -> None:
        self._running = running
        self.initialized = False
        self.started = False
        self.stopped = False

    async def initialize(self) -> None:
        self.initialized = True

    async def start(self) -> None:
        self.started = True
        self._running = True

    async def stop(self) -> None:
        self.stopped = True
        self._running = False


class _DummyHistoryService:
    def __init__(self, count: int) -> None:
        self.count = count

    async def purge_ephemeral_items(self) -> int:
        return self.count


@pytest.fixture
def state() -> _DummyState:
    return _DummyState()


@pytest.fixture
def history_service() -> _DummyHistoryService:
    return _DummyHistoryService(0)


@pytest.fixture
def log_handler() -> _DummyHandler:
    return _DummyHandler()


@pytest.fixture(autouse=True)
def patch_app_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    state: _DummyState,
    history_service: _DummyHistoryService,
    log_handler: _DummyHandler,
) -> None:
    monkeypatch.setattr(app_module, "get_app_state", lambda: state)
    monkeypatch.setattr(app_module, "get_history_service", lambda: history_service)
    monkeypatch.setattr(app_module, "get_log_ws_handler", lambda: log_handler)


@pytest.mark.asyncio
async def test_lifespan_manages_scheduler_startup_and_shutdown(
    state: _DummyState,
    history_service: _DummyHistoryService,
    log_handler: _DummyHandler,
) -> None:
    history_service.count = 2
    scheduler = _DummyScheduler(running=False)

    app = app_module.FastAPI()
    app.extra["scheduler"] = scheduler

    async with app_module.lifespan(app):
        assert state.scheduler_set is scheduler
        assert scheduler.initialized is True
        assert scheduler.started is True

    assert state.shutdown_called is True
    assert scheduler.stopped is True


@pytest.mark.asyncio
async def test_lifespan_handles_missing_scheduler_and_public_anilist_errors(
    monkeypatch: pytest.MonkeyPatch,
    state: _DummyState,
) -> None:
    async def _boom(self: _DummyState) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(_DummyState, "ensure_public_anilist", _boom)

    async with app_module.lifespan(app_module.FastAPI()):
        pass

    assert state.shutdown_called is True


def test_create_app_serves_spa_and_domain_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_file = tmp_path / "index.html"
    index_file.write_text("<html>SPA</html>", encoding="utf-8")
    monkeypatch.setattr(app_module, "FRONTEND_BUILD_DIR", tmp_path, raising=False)
    monkeypatch.setattr(app_module.log, "level", logging.INFO)

    spa_app = app_module.create_app()

    with TestClient(spa_app) as client:
        assert client.get("/missing").text == "<html>SPA</html>"
        assert client.get("/api/missing").status_code == 404

    handler = spa_app.exception_handlers[AnibridgeError]
    request = Request(
        {
            "type": "http",
            "path": "/boom",
            "headers": [],
            "query_string": b"",
            "method": "GET",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
        }
    )
    error = handler(request, ProfileNotFoundError("missing profile"))
    assert isinstance(error, Response)
    assert error.status_code == 404
    assert error.body == (
        b'{"error":"ProfileNotFoundError",'
        b'"detail":"\'missing profile\'","path":"/boom"}'
    )


def test_create_app_skips_spa_when_frontend_assets_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_dir = tmp_path / "frontend-build"
    monkeypatch.setattr(app_module, "FRONTEND_BUILD_DIR", missing_dir, raising=False)
    monkeypatch.setattr(app_module.log, "level", logging.DEBUG)

    app = app_module.create_app()

    middleware_classes = {middleware.cls for middleware in app.user_middleware}
    assert app.router.routes
    assert app_module.RequestLoggingMiddleware in middleware_classes
