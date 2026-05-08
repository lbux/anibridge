"""Route for basic liveness check (not readiness)."""

from typing import Literal

import msgspec
from fastapi.routing import APIRouter

from anibridge.app.models.schemas._pydantic_msgspec import PydanticMsgspecMixin

router = APIRouter()


class LivezResponse(PydanticMsgspecMixin, msgspec.Struct):
    """Minimal liveness payload for unauthenticated probes."""

    status: Literal["ok"] = "ok"


@router.get("/livez", include_in_schema=False, response_model=LivezResponse)
@router.get("/healthz", include_in_schema=False, response_model=LivezResponse)
async def livez() -> LivezResponse:
    """Liveness check endpoint.

    Returns:
        LivezResponse: Always returns status "ok" if the application is running.
    """
    return LivezResponse()
