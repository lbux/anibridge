"""Route for readiness check."""

from enum import StrEnum

import msgspec
from fastapi import Response
from fastapi.routing import APIRouter

from anibridge.app.models.schemas._pydantic_msgspec import PydanticMsgspecMixin
from anibridge.app.web.state import get_app_state

router = APIRouter()


class ReadyzStatus(StrEnum):
    """Enumerated readiness status values."""

    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ReadyzProfilesResponse(PydanticMsgspecMixin, msgspec.Struct):
    """Aggregate profile counts exposed by the readiness probe."""

    configured: int
    initialized: int
    failed: int


class ReadyzResponse(PydanticMsgspecMixin, msgspec.Struct):
    """Minimal readiness payload for unauthenticated probes."""

    status: ReadyzStatus
    ready: bool
    scheduler_running: bool
    profiles: ReadyzProfilesResponse


@router.get("/readyz", include_in_schema=False, response_model=ReadyzResponse)
async def readyz(response: Response) -> ReadyzResponse:
    """Readiness check endpoint.

    Args:
        response (Response): FastAPI Response object to set status code.

    Returns:
        ReadyzResponse: Readiness status and profile summary.
    """
    scheduler = get_app_state().scheduler
    if scheduler is None:
        response.status_code = 503
        return ReadyzResponse(
            status=ReadyzStatus.UNAVAILABLE,
            ready=False,
            scheduler_running=False,
            profiles=ReadyzProfilesResponse(
                configured=0,
                initialized=0,
                failed=0,
            ),
        )

    configured_profiles = len(scheduler.global_config.profiles)
    initialized_profiles = len(scheduler.bridge_clients)
    failed_profiles = len(scheduler.failed_profile_errors)
    scheduler_running = scheduler.is_running
    ready = scheduler_running and failed_profiles == 0

    status = (
        ReadyzStatus.OK
        if ready
        else ReadyzStatus.DEGRADED
        if scheduler_running and initialized_profiles
        else ReadyzStatus.UNAVAILABLE
    )
    response.status_code = 200 if ready else 503
    return ReadyzResponse(
        status=status,
        ready=ready,
        scheduler_running=scheduler_running,
        profiles=ReadyzProfilesResponse(
            configured=configured_profiles,
            initialized=initialized_profiles,
            failed=failed_profiles,
        ),
    )
