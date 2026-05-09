"""Litestar websocket routes."""

from litestar.router import Router

from anibridge.app.web.routes.ws.history import router as history_router
from anibridge.app.web.routes.ws.logs import router as logs_router
from anibridge.app.web.routes.ws.status import router as status_router

__all__ = ["router"]

router = Router(
    path="/ws",
    route_handlers=[history_router, logs_router, status_router],
)
