"""Litestar application factory and setup."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from logging import DEBUG, Logger
from typing import cast

from litestar.app import Litestar
from litestar.connection.request import Request as LitestarRequest
from litestar.file_system import BaseLocalFileSystem
from litestar.handlers.http_handlers.decorators import get
from litestar.middleware.base import ASGIMiddleware
from litestar.response.base import Response as LitestarResponse
from litestar.response.file import ASGIFileResponse
from litestar.static_files.base import StaticFiles
from litestar.types.internal_types import ControllerRouterHandler

from anibridge.app import config, log
from anibridge.app.core.sched import SchedulerClient
from anibridge.app.exceptions import AnibridgeError
from anibridge.app.utils.paths import PROJECT_ROOT
from anibridge.app.web.middlewares.basic_auth import BasicAuthMiddleware
from anibridge.app.web.middlewares.request_logging import RequestLoggingMiddleware
from anibridge.app.web.routes.api import router as api_router
from anibridge.app.web.routes.webhook import router as webhook_router
from anibridge.app.web.routes.ws import router as ws_router
from anibridge.app.web.routes.z import router as z_router
from anibridge.app.web.services.history_service import get_history_service
from anibridge.app.web.services.logging_handler import get_log_ws_handler
from anibridge.app.web.state import get_app_state

__all__ = ["create_app"]

FRONTEND_BUILD_DIR = PROJECT_ROOT / "frontend" / "build"


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Application lifespan context manager.

    Args:
        app (Litestar): The Litestar application instance.

    Returns:
        AsyncGenerator: The application lifespan context manager.
    """
    scheduler: SchedulerClient | None = getattr(app.state, "scheduler", None)
    if scheduler is None:
        log.info("Web - No scheduler passed; external lifecycle management expected")
    else:
        get_app_state().set_scheduler(scheduler)
        if not scheduler._running:
            await scheduler.initialize()
            await scheduler.start()
            log.success("Web - Scheduler started for web UI")

    try:
        await get_app_state().ensure_public_anilist()
    except Exception:
        log.debug("Web - Failed to initialize public AniList client at startup")

    purged_history_count = await get_history_service().purge_ephemeral_items()
    if purged_history_count:
        log.info(
            "Web - Deleted %s ephemeral dry-run history entries at startup",
            purged_history_count,
        )

    root_logger = cast(Logger, log)
    log_ws_handler = get_log_ws_handler()
    if log_ws_handler not in root_logger.handlers:
        root_logger.addHandler(log_ws_handler)
    try:
        loop = asyncio.get_running_loop()
        log_ws_handler.set_event_loop(loop)
    except Exception:
        pass
    try:
        yield
    finally:
        await get_app_state().shutdown()
        if scheduler and scheduler._running:
            await scheduler.stop()


def litestar_domain_exception_handler(
    request: LitestarRequest, exc: Exception
) -> LitestarResponse[dict[str, str]]:
    """Handle AniBridge errors inside the Litestar shell."""
    status_code = getattr(exc.__class__, "status_code", 500)
    return LitestarResponse(
        content={
            "error": exc.__class__.__name__,
            "detail": str(exc) or exc.__class__.__doc__ or "",
            "path": request.url.path,
        },
        status_code=status_code,
    )


async def _serve_frontend_asset(
    path: str, *, is_head_response: bool = False
) -> ASGIFileResponse:
    return await StaticFiles(
        is_html_mode=False,
        directories=[FRONTEND_BUILD_DIR],
        file_system=BaseLocalFileSystem(),
        send_as_attachment=False,
    ).handle(
        path=path,
        is_head_response=is_head_response,
    )


@get(path=["/", "/{path:path}"], include_in_schema=False)
async def serve_spa(
    path: str = "",
) -> ASGIFileResponse:
    """Serve built frontend assets and fall back to the SPA entrypoint."""
    normalized_path = path.lstrip("/")

    if bool(normalized_path) and "." in normalized_path.rsplit("/", 1)[-1]:
        return await _serve_frontend_asset(normalized_path)

    return await _serve_frontend_asset("index.html")


def create_app(scheduler: SchedulerClient | None = None) -> Litestar:
    """Create the Litestar application.

    Args:
        scheduler (SchedulerClient | None): The scheduler client instance.

    Returns:
        Litestar: The created Litestar application.
    """
    middleware: list[ASGIMiddleware] = []

    # Add request logging middleware if in debug mode
    if cast(Logger, log).level <= DEBUG:
        middleware.append(RequestLoggingMiddleware())
        log.debug("Web - Request logging enabled (debug mode)")

    # Add basic auth middleware if configured
    if config.web.has_auth:
        middleware.append(
            BasicAuthMiddleware(
                username=config.web.basic_auth.username,
                password=config.web.basic_auth.password.get_secret_value()
                if config.web.basic_auth.password
                else None,
                htpasswd_path=config.web.basic_auth.htpasswd_path,
                realm=config.web.basic_auth.realm,
            )
        )
        log.info("Web - HTTP Basic Authentication enabled for web UI")

    route_handlers: list[ControllerRouterHandler] = [
        api_router,
        ws_router,
        webhook_router,
        z_router,
    ]

    index_file = FRONTEND_BUILD_DIR / "index.html"
    if not FRONTEND_BUILD_DIR.exists():
        log.warning(
            "Web - Frontend build directory does not exist, no SPA will be served"
        )
    elif not index_file.exists():
        log.error("Web - Frontend index file does not exist, no SPA will be served")
    else:
        route_handlers.append(serve_spa)

    app = Litestar(
        route_handlers=route_handlers,
        middleware=middleware,
        lifespan=[lifespan],
        exception_handlers={AnibridgeError: litestar_domain_exception_handler},
    )

    if scheduler:
        app.state.scheduler = scheduler

    return app
