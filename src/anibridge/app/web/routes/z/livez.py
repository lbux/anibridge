"""Route for basic liveness check (not readiness)."""

from typing import Literal

import msgspec
from litestar.handlers.http_handlers.decorators import get
from litestar.router import Router

__all__ = ["router"]


class LivezResponse(msgspec.Struct):
    """Minimal liveness payload for unauthenticated probes."""

    status: Literal["ok"] = "ok"


@get(path=["/livez", "/healthz"], include_in_schema=False)
async def livez() -> LivezResponse:
    """Liveness check endpoint.

    Returns:
        LivezResponse: Always returns status "ok" if the application is running.
    """
    return LivezResponse()


router = Router(path="", route_handlers=[livez])
