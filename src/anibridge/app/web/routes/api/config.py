"""Configuration management API endpoints."""

from typing import Annotated

import msgspec
from litestar.exceptions.http_exceptions import HTTPException
from litestar.handlers.http_handlers.decorators import get, post
from litestar.params import Body
from litestar.router import Router
from pydantic import ValidationError

from anibridge.app.config.settings import AnibridgeConfig, get_config
from anibridge.app.exceptions import SchedulerUnavailableError
from anibridge.app.web.services.configuration_service import get_configuration_service

__all__ = ["router"]


class ConfigDocumentResponse(msgspec.Struct):
    config_path: str
    file_exists: bool
    content: str
    schema: dict[str, object]
    mtime: int | None = None


class ConfigDocumentUpdateRequest(msgspec.Struct):
    content: str = ""
    expected_mtime: int | None = None


class ConfigUpdateResponse(msgspec.Struct):
    ok: bool
    profiles: list[str]
    requires_restart: bool = True
    mtime: int | None = None


def require_config_api_access() -> None:
    """Ensure configuration API access is not exposed without explicit opt-in."""
    web_config = getattr(globals().get("runtime_config"), "web", None)
    if web_config is None:
        web_config = get_config().web
    if web_config.has_auth or web_config.allow_config_without_auth:
        return

    raise HTTPException(
        status_code=403,
        detail=(
            "Configuration API is disabled when web authentication is not configured. "
            "Configure web.basic_auth or set "
            "web.allow_config_without_auth=true to override."
        ),
    )


@get(path="", sync_to_thread=True)
def get_configuration() -> ConfigDocumentResponse:
    """Return the current configuration as raw YAML text.

    Returns:
        ConfigDocumentResponse: The configuration document details.
    """
    require_config_api_access()
    try:
        payload = get_configuration_service().load_document_text()
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc.errors()),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    document = dict(payload)
    document["schema"] = AnibridgeConfig.model_json_schema()
    return msgspec.convert(document, type=ConfigDocumentResponse)


@post(path="", status_code=200)
async def update_configuration(
    data: Annotated[ConfigDocumentUpdateRequest, Body()],
) -> ConfigUpdateResponse:
    """Persist the provided configuration document.

    Args:
        data (ConfigDocumentUpdateRequest): The configuration update request.

    Returns:
        ConfigUpdateResponse: The result of the update operation.
    """
    require_config_api_access()
    try:
        (
            config,
            requires_restart,
            mtime,
        ) = await get_configuration_service().save_document_text(
            data.content,
            expected_mtime=data.expected_mtime,
        )
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc.errors()),
        ) from exc
    except SchedulerUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return ConfigUpdateResponse(
        ok=True,
        profiles=sorted(config.profiles.keys()),
        requires_restart=requires_restart,
        mtime=mtime,
    )


@get(path="/openapi.json", sync_to_thread=True)
def get_openapi_schema() -> dict[str, object]:
    """Return the OpenAPI schema for the configuration API.

    Returns:
        dict: OpenAPI schema
    """
    require_config_api_access()
    return AnibridgeConfig.model_json_schema()


router = Router(
    path="/config",
    route_handlers=[get_configuration, update_configuration, get_openapi_schema],
)
