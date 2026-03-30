"""Tests for logs websocket endpoint."""

from typing import Any, cast

import pytest
from fastapi import WebSocketDisconnect

from anibridge.app.web.routes.ws import logs as logs_ws_module


class _FakeLogsWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.removed = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        raise WebSocketDisconnect


@pytest.mark.asyncio
async def test_logs_websocket_registers_and_unregisters(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class _Handler:
        async def add(self, ws) -> None:
            calls.append(("add", ws))

        async def remove(self, ws) -> None:
            calls.append(("remove", ws))

    websocket = _FakeLogsWebSocket()
    monkeypatch.setattr(logs_ws_module, "get_log_ws_handler", lambda: _Handler())

    await logs_ws_module.logs_ws(cast(Any, websocket))

    assert websocket.accepted is True
    assert [name for name, _ in calls] == ["add", "remove"]
