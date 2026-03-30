"""Route for basic liveness check (not readiness)."""

from typing import Literal

from fastapi.routing import APIRouter
from pydantic import BaseModel

router = APIRouter()


class LivezResponse(BaseModel):
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
