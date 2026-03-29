"""Tests for sync API endpoints."""

import pytest

from anibridge.app.exceptions import SchedulerNotInitializedError
from anibridge.app.web.routes.api import sync as sync_api_module


class _DummyScheduler:
    def __init__(self) -> None:
        self.reinitialized_profiles: list[str] = []

    async def reinitialize_profile(self, profile: str) -> None:
        self.reinitialized_profiles.append(profile)


class _DummyAppState:
    def __init__(self, scheduler: _DummyScheduler | None) -> None:
        self.scheduler = scheduler


@pytest.mark.asyncio
async def test_reinitialize_profile_calls_scheduler(monkeypatch) -> None:
    """Reinitialize endpoint should target the requested profile."""
    scheduler = _DummyScheduler()
    state = _DummyAppState(scheduler=scheduler)
    monkeypatch.setattr(sync_api_module, "get_app_state", lambda: state)

    response = await sync_api_module.reinitialize_profile("broken")

    assert response.ok is True
    assert scheduler.reinitialized_profiles == ["broken"]


@pytest.mark.asyncio
async def test_reinitialize_profile_requires_scheduler(monkeypatch) -> None:
    """Reinitialize endpoint should fail when scheduler is unavailable."""
    state = _DummyAppState(scheduler=None)
    monkeypatch.setattr(sync_api_module, "get_app_state", lambda: state)

    with pytest.raises(SchedulerNotInitializedError):
        await sync_api_module.reinitialize_profile("broken")
