"""Litestar route aggregators for the web application."""

from litestar.router import Router

from anibridge.app.web.routes.api import router as api_router
from anibridge.app.web.routes.webhook import router as webhook_router
from anibridge.app.web.routes.ws import router as ws_router
from anibridge.app.web.routes.z import router as z_router

__all__ = ["router"]

router = Router(
    path="", route_handlers=[api_router, ws_router, webhook_router, z_router]
)
