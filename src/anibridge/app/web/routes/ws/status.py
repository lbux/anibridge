"""Websocket endpoint for periodic status snapshots."""

import asyncio

from litestar.connection.websocket import WebSocket
from litestar.exceptions.websocket_exceptions import WebSocketDisconnect
from litestar.handlers.websocket_handlers.route_handler import websocket
from litestar.router import Router

from anibridge.app.web.state import get_app_state

__all__ = ["router"]

_IDLE_POLL_INTERVAL = 1.0
_ACTIVE_SYNC_INTERVAL = 0.5


@websocket(path="")
async def status_ws(socket: WebSocket) -> None:
    """Websocket endpoint for periodic status snapshots.

    Args:
        socket (WebSocket): The WebSocket connection instance.
    """
    await socket.accept()
    app_state = get_app_state()
    try:
        while True:
            scheduler = app_state.scheduler
            data = (
                {"profiles": await scheduler.get_status()}
                if scheduler
                else {"profiles": {}}
            )
            await socket.send_json(data)

            # If any profile reports an active current_sync, use a fast refresh.
            # Otherwise, wait for an explicit status-change notification (or timeout).
            try:
                profiles = data.get("profiles", {})
                syncing = any(
                    (p.get("status", {}).get("current_sync") or {}).get("state")
                    == "running"
                    for p in profiles.values()
                )
            except Exception:
                syncing = False

            wait_timeout = _ACTIVE_SYNC_INTERVAL if syncing else _IDLE_POLL_INTERVAL

            try:
                await asyncio.wait_for(socket.receive_text(), timeout=wait_timeout)
            except TimeoutError:
                continue
    except WebSocketDisconnect:
        pass


router = Router(path="/status", route_handlers=[status_ws])
