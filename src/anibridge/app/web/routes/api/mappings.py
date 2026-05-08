"""API endpoints for mappings (v3 graph)."""

from typing import Annotated

import msgspec
from litestar.exceptions.http_exceptions import HTTPException
from litestar.handlers.http_handlers.decorators import get, post, put
from litestar.params import Body
from litestar.router import Router

from anibridge.app.exceptions import (
    AniListFilterError,
    AniListSearchError,
    BooruQueryEvaluationError,
    BooruQuerySyntaxError,
    MappingIdMismatchError,
)
from anibridge.app.models.schemas.anilist import Media
from anibridge.app.web.services.mapping_overrides_service import (
    get_mapping_overrides_service,
)
from anibridge.app.web.services.mappings_query_spec import get_query_field_specs
from anibridge.app.web.services.mappings_service import get_mappings_service

__all__ = ["router"]


class MappingEdgeModel(msgspec.Struct):
    target_provider: str
    target_entry_id: str
    source_range: str
    target_scope: str | None = None
    destination_range: str | None = None
    sources: list[str] = msgspec.field(default_factory=list)


class MappingItemModel(msgspec.Struct):
    descriptor: str
    provider: str
    entry_id: str
    edges: list[MappingEdgeModel]
    scope: str | None = None
    custom: bool = False
    sources: list[str] = msgspec.field(default_factory=list)
    anilist: Media | None = None


class ListMappingsResponse(msgspec.Struct):
    items: list[MappingItemModel]
    total: int
    page: int
    per_page: int
    pages: int
    with_anilist: bool = False


class DeleteMappingResponse(msgspec.Struct):
    ok: bool


class RangeInputModel(msgspec.Struct):
    source_range: str
    destination_range: str | None = None


class TargetInputModel(msgspec.Struct):
    provider: str
    entry_id: str
    scope: str | None = None
    ranges: list[RangeInputModel] = msgspec.field(default_factory=list)
    deleted: bool = False


class MappingOverridePayload(msgspec.Struct):
    """Payload for creating or updating a mapping override."""

    descriptor: str
    targets: list[TargetInputModel] = msgspec.field(default_factory=list)


class MappingRangeViewModel(msgspec.Struct):
    source_range: str
    origin: str
    upstream: str | None = None
    custom: str | None = None
    effective: str | None = None
    inherited: bool = False


class MappingTargetViewModel(msgspec.Struct):
    descriptor: str
    provider: str
    entry_id: str
    origin: str
    scope: str | None = None
    deleted: bool = False
    ranges: list[MappingRangeViewModel] = msgspec.field(default_factory=list)


class MappingLayersModel(msgspec.Struct):
    upstream: dict[str, dict[str, str | None] | None] = msgspec.field(
        default_factory=dict
    )
    custom: dict[str, dict[str, str | None] | None] = msgspec.field(
        default_factory=dict
    )
    effective: dict[str, dict[str, str | None] | None] = msgspec.field(
        default_factory=dict
    )


class MappingDetailModel(msgspec.Struct):
    descriptor: str
    provider: str
    entry_id: str
    scope: str | None = None
    layers: MappingLayersModel = msgspec.field(default_factory=MappingLayersModel)
    targets: list[MappingTargetViewModel] = msgspec.field(default_factory=list)


class FieldCapabilityModel(msgspec.Struct):
    key: str
    type: str
    operators: list[str]
    aliases: list[str] = msgspec.field(default_factory=list)
    values: list[str] | None = None
    desc: str | None = None


class QueryCapabilitiesResponse(msgspec.Struct):
    fields: list[FieldCapabilityModel]


@get(path="")
async def list_mappings(
    page: int = 1,
    per_page: int = 25,
    q: str | None = None,
    custom_only: bool = False,
    with_anilist: bool = False,
) -> ListMappingsResponse:
    svc = get_mappings_service()

    async def cancel_check() -> bool:
        return False

    try:
        raw_items, total = await svc.list_mappings(
            page=page,
            per_page=per_page,
            q=q,
            custom_only=custom_only,
            with_anilist=with_anilist,
            cancel_check=cancel_check,
        )
    except (
        BooruQuerySyntaxError,
        BooruQueryEvaluationError,
        AniListFilterError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AniListSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    items = msgspec.convert(raw_items, type=list[MappingItemModel])
    pages = (total + per_page - 1) // per_page if per_page else 1
    return ListMappingsResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        with_anilist=with_anilist,
    )


@get(path="/query-capabilities", sync_to_thread=True)
def query_capabilities() -> QueryCapabilitiesResponse:
    specs = get_query_field_specs()
    fields = [
        FieldCapabilityModel(
            key=spec.key,
            aliases=list(spec.aliases),
            type=str(spec.type.value),
            operators=[op.value for op in spec.operators],
            values=list(spec.values) if spec.values is not None else None,
            desc=spec.desc,
        )
        for spec in specs
    ]
    return QueryCapabilitiesResponse(fields=fields)


@get(path="/{descriptor:str}")
async def get_mapping(descriptor: str) -> MappingDetailModel:
    svc = get_mapping_overrides_service()
    data = await svc.get_mapping_detail(descriptor)
    return msgspec.convert(data, type=MappingDetailModel)


@post(path="", status_code=200)
async def create_mapping(
    data: Annotated[MappingOverridePayload, Body()],
) -> MappingDetailModel:
    svc = get_mapping_overrides_service()
    saved = await svc.save_override(
        descriptor=data.descriptor,
        targets=msgspec.to_builtins(data.targets),
    )
    return msgspec.convert(saved, type=MappingDetailModel)


@put(path="/{descriptor:str}")
async def update_mapping(
    descriptor: str,
    data: Annotated[MappingOverridePayload, Body()],
) -> MappingDetailModel:
    if data.descriptor != descriptor:
        raise MappingIdMismatchError("descriptor in path and body must match")

    svc = get_mapping_overrides_service()
    saved = await svc.save_override(
        descriptor=data.descriptor,
        targets=msgspec.to_builtins(data.targets),
    )
    return msgspec.convert(saved, type=MappingDetailModel)


router = Router(
    path="/mappings",
    route_handlers=[
        list_mappings,
        query_capabilities,
        get_mapping,
        create_mapping,
        update_mapping,
    ],
)
