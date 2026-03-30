"""Shared helpers for API route tests."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from anibridge.app.web.routes.api import config as config_api_module


@pytest.fixture
def api_client_factory() -> Callable[[APIRouter, str], TestClient]:
    """Build lightweight FastAPI clients around individual routers."""

    def _factory(router: APIRouter, prefix: str) -> TestClient:
        app = FastAPI()
        app.include_router(router, prefix=prefix)
        return TestClient(app)

    return _factory


@pytest.fixture
def api_client_for(
    api_client_factory: Callable[[APIRouter, str], TestClient],
) -> Callable[[Any, str], TestClient]:
    """Build a router client directly from a route module."""

    def _factory(route_module: Any, prefix: str) -> TestClient:
        return api_client_factory(route_module.router, prefix)

    return _factory


@pytest.fixture
def set_config_api_access(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Override config API auth settings for route access tests."""

    def _configure(
        *,
        has_auth: bool = False,
        allow_config_without_auth: bool = False,
    ) -> None:
        monkeypatch.setattr(
            config_api_module,
            "runtime_config",
            SimpleNamespace(
                web=SimpleNamespace(
                    has_auth=has_auth,
                    allow_config_without_auth=allow_config_without_auth,
                )
            ),
            raising=False,
        )

    return _configure


class _AppState(SimpleNamespace):
    """Mutable app-state stub for route tests."""

    restart_requested: bool

    def request_restart(self) -> None:
        self.restart_requested = True


@pytest.fixture
def make_app_state() -> Callable[..., _AppState]:
    """Construct lightweight app-state stubs with sensible defaults."""

    def _factory(**overrides: Any) -> _AppState:
        return _AppState(
            scheduler=overrides.pop("scheduler", None),
            started_at=overrides.pop("started_at", None),
            restart_requested=overrides.pop("restart_requested", False),
            **overrides,
        )

    return _factory


@pytest.fixture
def patch_app_state(
    monkeypatch: pytest.MonkeyPatch,
    make_app_state: Callable[..., _AppState],
) -> Callable[..., _AppState]:
    """Patch a route module to use a disposable app-state stub."""

    def _patch(route_module: Any, **overrides: Any) -> _AppState:
        state = make_app_state(**overrides)
        monkeypatch.setattr(route_module, "get_app_state", lambda: state)
        return state

    return _patch
