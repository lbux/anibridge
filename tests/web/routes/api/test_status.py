"""Tests for status API routes."""

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from anibridge.app.web.routes.api import status as status_api_module


class _DummyScheduler:
    async def get_status(self) -> dict[str, Any]:
        return {
            "primary": {
                "config": {
                    "library_namespace": "plex",
                    "list_namespace": "anilist",
                    "library_user": "Library User",
                    "list_user": "List User",
                    "poll_interval": 60,
                    "scan_interval": "0 * * * *",
                    "scan_modes": ["poll", "periodic"],
                    "full_scan": True,
                    "destructive_sync": False,
                },
                "status": {
                    "running": True,
                    "last_synced": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                    "current_sync": {"state": "running"},
                    "initialization_error": None,
                },
            }
        }

    async def get_runtime_metrics(self) -> dict[str, Any]:
        return {"coordinator": {"running": True}}


@pytest.mark.asyncio
async def test_status_route_returns_empty_without_scheduler(patch_app_state) -> None:
    patch_app_state(status_api_module, scheduler=None)

    response = await status_api_module.status()

    assert response.profiles == {}
    assert response.scheduler is None


@pytest.mark.asyncio
async def test_status_route_serializes_scheduler_payload(patch_app_state) -> None:
    patch_app_state(status_api_module, scheduler=cast(Any, _DummyScheduler()))

    response = await status_api_module.status()

    profile = response.profiles["primary"]
    assert profile.config.library_namespace == "plex"
    assert profile.config.scan_modes == ["poll", "periodic"]
    assert profile.status.current_sync == {"state": "running"}
    assert response.scheduler == {"coordinator": {"running": True}}


def test_construct_profile_status_handles_missing_fields() -> None:
    profile = status_api_module.construct_profile_status(
        {"config": {"library_namespace": "plex", "list_namespace": "anilist"}}
    )

    assert profile.config.library_namespace == "plex"
    assert profile.status.running is False
    assert profile.status.last_synced is None
