"""Tests for status websocket endpoint."""

from typing import Any, cast

import pytest
from litestar.connection.websocket import WebSocket
from litestar.exceptions.websocket_exceptions import WebSocketDisconnect

from anibridge.app.web.routes.ws import status as status_ws_module


class _FakeStatusWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)

    async def receive_text(self) -> str:
        raise WebSocketDisconnect(detail="disconnect event")


@pytest.mark.asyncio
async def test_status_websocket_streams_scheduler_state(monkeypatch) -> None:
    websocket = _FakeStatusWebSocket()

    class _Scheduler:
        async def get_status(self) -> dict[str, Any]:
            return {"default": {"status": {"current_sync": {"state": "running"}}}}

    async def _wait_for(awaitable, **kwargs):
        timeout = kwargs["timeout"]
        assert timeout == status_ws_module._ACTIVE_SYNC_INTERVAL
        return await awaitable

    class _State:
        scheduler = _Scheduler()

    monkeypatch.setattr(
        status_ws_module,
        "get_app_state",
        lambda: _State(),
    )
    monkeypatch.setattr(status_ws_module.asyncio, "wait_for", _wait_for)

    await status_ws_module.status_ws.fn(cast(WebSocket, websocket))

    assert websocket.accepted is True
    assert websocket.messages == [
        {"profiles": {"default": {"status": {"current_sync": {"state": "running"}}}}}
    ]


@pytest.mark.asyncio
async def test_status_websocket_handles_missing_scheduler(monkeypatch) -> None:
    websocket = _FakeStatusWebSocket()

    class _State:
        scheduler = None

    async def _wait_for(awaitable, **kwargs):
        timeout = kwargs["timeout"]
        assert timeout == status_ws_module._IDLE_POLL_INTERVAL
        return await awaitable

    monkeypatch.setattr(
        status_ws_module,
        "get_app_state",
        lambda: _State(),
    )
    monkeypatch.setattr(status_ws_module.asyncio, "wait_for", _wait_for)

    await status_ws_module.status_ws.fn(cast(WebSocket, websocket))

    assert websocket.messages == [{"profiles": {}}]
