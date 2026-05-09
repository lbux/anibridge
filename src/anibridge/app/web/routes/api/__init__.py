"""Litestar API routes."""

from litestar.router import Router

from anibridge.app.web.routes.api.backups import router as backups_router
from anibridge.app.web.routes.api.config import router as config_router
from anibridge.app.web.routes.api.history import router as history_router
from anibridge.app.web.routes.api.logs import router as logs_router
from anibridge.app.web.routes.api.mappings import router as mappings_router
from anibridge.app.web.routes.api.pins import router as pins_router
from anibridge.app.web.routes.api.status import router as status_router
from anibridge.app.web.routes.api.sync import router as sync_router
from anibridge.app.web.routes.api.system import router as system_router

__all__ = ["router"]

router = Router(
    path="/api",
    route_handlers=[
        history_router,
        backups_router,
        config_router,
        mappings_router,
        pins_router,
        logs_router,
        status_router,
        sync_router,
        system_router,
    ],
)
