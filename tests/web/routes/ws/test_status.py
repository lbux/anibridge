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
        assert seconds == 0.5
        raise WebSocketDisconnect

    monkeypatch.setattr(
        status_ws_module,
        "get_app_state",
        lambda: type("State", (), {"scheduler": _Scheduler()})(),
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

    async def _disconnect(seconds: float) -> None:
        assert seconds == 5.0
        raise WebSocketDisconnect

    monkeypatch.setattr(
        status_ws_module,
        "get_app_state",
        lambda: type("State", (), {"scheduler": None})(),
    )
    monkeypatch.setattr(status_ws_module.asyncio, "sleep", _disconnect)

    await status_ws_module.status_ws(cast(Any, websocket))

    assert websocket.messages == [{"profiles": {}}]
