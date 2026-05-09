"""Litestar z-suffix route aggregator."""

from litestar.router import Router

from anibridge.app.web.routes.z.livez import router as livez_router
from anibridge.app.web.routes.z.readyz import router as readyz_router

__all__ = ["router"]

router = Router(path="", route_handlers=[livez_router, readyz_router])
