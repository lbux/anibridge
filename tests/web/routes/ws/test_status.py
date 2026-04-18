"""Tests for status websocket endpoint."""

from typing import Any, cast

import pytest
from fastapi import WebSocketDisconnect

from anibridge.app.web.routes.ws import status as status_ws_module


class _FakeStatusWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


@pytest.mark.asyncio
async def test_status_websocket_streams_scheduler_state(monkeypatch) -> None:
    websocket = _FakeStatusWebSocket()

    class _Scheduler:
        async def get_status(self) -> dict:
            return {"default": {"status": {"current_sync": {"state": "running"}}}}

    async def _disconnect(seconds: float) -> None:
        assert seconds == status_ws_module._ACTIVE_SYNC_INTERVAL
        raise WebSocketDisconnect

    class _State:
        scheduler = _Scheduler()

    monkeypatch.setattr(
        status_ws_module,
        "get_app_state",
        lambda: _State(),
    )
    monkeypatch.setattr(status_ws_module.asyncio, "sleep", _disconnect)

    await status_ws_module.status_ws(cast(Any, websocket))

    assert websocket.accepted is True
    assert websocket.messages == [
        {"profiles": {"default": {"status": {"current_sync": {"state": "running"}}}}}
    ]


@pytest.mark.asyncio
async def test_status_websocket_handles_missing_scheduler(monkeypatch) -> None:
    websocket = _FakeStatusWebSocket()

    class _State:
        scheduler = None

        async def wait_status_change(self, *, max_wait: float) -> None:
            raise WebSocketDisconnect

    monkeypatch.setattr(
        status_ws_module,
        "get_app_state",
        lambda: _State(),
    )

    await status_ws_module.status_ws(cast(Any, websocket))

    assert websocket.messages == [{"profiles": {}}]
