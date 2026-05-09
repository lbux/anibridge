"""Litestar webhook route aggregator."""

from litestar.router import Router

from anibridge.app.web.routes.webhook.provider import router as provider_router

__all__ = ["router"]

router = Router(path="/webhook", route_handlers=[provider_router])
