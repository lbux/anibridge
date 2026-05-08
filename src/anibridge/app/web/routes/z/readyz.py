"""Route for readiness check."""

from enum import StrEnum

import msgspec
from litestar.handlers.http_handlers.decorators import get
from litestar.response.base import Response
from litestar.router import Router

from anibridge.app.web.state import get_app_state

__all__ = ["router"]


class ReadyzStatus(StrEnum):
    """Enumerated readiness status values."""

    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ReadyzProfilesResponse(msgspec.Struct):
    """Aggregate profile counts exposed by the readiness probe."""

    configured: int
    initialized: int
    failed: int


class ReadyzResponse(msgspec.Struct):
    """Minimal readiness payload for unauthenticated probes."""

    status: ReadyzStatus
    ready: bool
    scheduler_running: bool
    profiles: ReadyzProfilesResponse


@get(path="/readyz", include_in_schema=False)
async def readyz() -> Response[ReadyzResponse]:
    """Readiness check endpoint.

    Returns:
        ReadyzResponse: Readiness status and profile summary.
    """
    scheduler = get_app_state().scheduler
    if scheduler is None:
        return Response(
            content=ReadyzResponse(
                status=ReadyzStatus.UNAVAILABLE,
                ready=False,
                scheduler_running=False,
                profiles=ReadyzProfilesResponse(
                    configured=0,
                    initialized=0,
                    failed=0,
                ),
            ),
            status_code=503,
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
    return Response(
        content=ReadyzResponse(
            status=status,
            ready=ready,
            scheduler_running=scheduler_running,
            profiles=ReadyzProfilesResponse(
                configured=configured_profiles,
                initialized=initialized_profiles,
                failed=failed_profiles,
            ),
        ),
        status_code=200 if ready else 503,
    )


router = Router(path="", route_handlers=[readyz])
