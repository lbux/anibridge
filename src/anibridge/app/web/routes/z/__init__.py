"""z-suffix route aggregator."""

from fastapi.routing import APIRouter

from anibridge.app.web.routes.z.livez import router as livez_router
from anibridge.app.web.routes.z.readyz import router as readyz_router

__all__ = ["router"]

router = APIRouter()
router.include_router(livez_router, prefix="")
router.include_router(readyz_router, prefix="")
