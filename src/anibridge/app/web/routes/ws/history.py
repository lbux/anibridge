"""WebSocket endpoint for real-time timeline updates."""

import asyncio

from fastapi.routing import APIRouter
from fastapi.websockets import WebSocket, WebSocketDisconnect

from anibridge.app.web.services.history_service import get_history_service

__all__ = ["router"]

router = APIRouter()


@router.websocket("/{profile}")
async def history_websocket(websocket: WebSocket, profile: str) -> None:
    """Stream live history updates to client.

    Polls for latest id and pushes only cursor updates when it changes.
    """
    await websocket.accept()

    outcome = websocket.query_params.get("outcome") or None
    last_latest_id: int | None = None
    history_service = get_history_service()

    try:
        while True:
            latest_id = await history_service.get_latest_id(
                profile=profile, outcome=outcome
            )
            if latest_id != last_latest_id:
                last_latest_id = latest_id
                await websocket.send_json(
                    {
                        "profile": profile,
                        "outcome": outcome,
                        "latest_id": latest_id,
                    }
                )

            await asyncio.sleep(3)

    except WebSocketDisconnect:
        pass
    except Exception:
        await websocket.close()
