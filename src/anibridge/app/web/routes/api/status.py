"""API status endpoints."""

import msgspec
from litestar.handlers.http_handlers.decorators import get
from litestar.router import Router

from anibridge.app.web.state import get_app_state

__all__ = [
    "ProfileConfigModel",
    "ProfileRuntimeStatusModel",
    "ProfileStatusModel",
    "construct_profile_status",
    "router",
    "status",
]


class ProfileConfigModel(msgspec.Struct):
    """Serialized profile configuration exposed to the web UI."""

    library_namespace: str
    list_namespace: str
    library_user: str | None = None
    list_user: str | None = None
    poll_interval: int | str | None = None
    scan_interval: int | str | None = None
    scan_modes: list[str] = msgspec.field(default_factory=list)
    full_scan: bool | None = None
    destructive_sync: bool | None = None


class ProfileRuntimeStatusModel(msgspec.Struct):
    """Runtime status of a profile exposed to the web UI."""

    running: bool
    last_synced: str | None = None
    current_sync: dict | None = None
    initialization_error: str | None = None


class ProfileStatusModel(msgspec.Struct):
    """Combined profile configuration and runtime status exposed to the web UI."""

    config: ProfileConfigModel
    status: ProfileRuntimeStatusModel


class StatusResponse(msgspec.Struct):
    profiles: dict[str, ProfileStatusModel]
    scheduler: dict | None = None


@get(path="")
async def status() -> StatusResponse:
    """Get the status of the application.

    Returns:
        StatusResponse: The serialized application status.
    """
    scheduler = get_app_state().scheduler
    if not scheduler:
        return StatusResponse(profiles={}, scheduler=None)
    raw = await scheduler.get_status()
    runtime_metrics = await scheduler.get_runtime_metrics()
    converted = {name: construct_profile_status(data) for name, data in raw.items()}
    return StatusResponse(profiles=converted, scheduler=runtime_metrics)


def construct_profile_status(data: dict) -> ProfileStatusModel:
    """Build trusted scheduler profile payloads without re-validating them."""
    cfg = data.get("config", {})
    st = data.get("status", {})
    return ProfileStatusModel(
        config=ProfileConfigModel(
            library_namespace=cfg.get("library_namespace"),
            list_namespace=cfg.get("list_namespace"),
            library_user=cfg.get("library_user"),
            list_user=cfg.get("list_user"),
            poll_interval=cfg.get("poll_interval"),
            scan_interval=cfg.get("scan_interval"),
            scan_modes=list(cfg.get("scan_modes") or []),
            full_scan=cfg.get("full_scan"),
            destructive_sync=cfg.get("destructive_sync"),
        ),
        status=ProfileRuntimeStatusModel(
            running=bool(st.get("running")),
            last_synced=st.get("last_synced"),
            current_sync=st.get("current_sync"),
            initialization_error=st.get("initialization_error"),
        ),
    )


router = Router(path="/status", route_handlers=[status])
