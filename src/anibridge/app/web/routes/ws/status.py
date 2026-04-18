"""Websocket endpoint for periodic status snapshots."""

import asyncio

from fastapi.routing import APIRouter
from fastapi.websockets import WebSocket, WebSocketDisconnect

from anibridge.app.web.state import get_app_state

__all__ = ["router"]

router = APIRouter()

_MAX_IDLE_INTERVAL = 10.0
_ACTIVE_SYNC_INTERVAL = 0.5


@router.websocket("")
async def status_ws(ws: WebSocket) -> None:
    """Websocket endpoint for periodic status snapshots.

    Args:
        ws (WebSocket): The WebSocket connection instance.
    """
    await ws.accept()
    app_state = get_app_state()
    try:
        while True:
            scheduler = app_state.scheduler
            data = (
                {"profiles": await scheduler.get_status()}
                if scheduler
                else {"profiles": {}}
            )
            await ws.send_json(data)

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

            if syncing:
                await asyncio.sleep(_ACTIVE_SYNC_INTERVAL)
            else:
                await app_state.wait_status_change(max_wait=_MAX_IDLE_INTERVAL)
    except WebSocketDisconnect:
        pass
