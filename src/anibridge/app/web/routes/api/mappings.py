"""API endpoints for mappings (v3 graph)."""

import asyncio
from typing import Annotated

import msgspec
from fastapi import Body, Request
from fastapi.exceptions import HTTPException
from fastapi.param_functions import Query
from fastapi.routing import APIRouter

from anibridge.app.exceptions import (
    AniListFilterError,
    AniListSearchError,
    BooruQueryEvaluationError,
    BooruQuerySyntaxError,
    MappingIdMismatchError,
)
from anibridge.app.models.schemas._pydantic_msgspec import PydanticMsgspecMixin
from anibridge.app.models.schemas.anilist import Media
from anibridge.app.web.services.mapping_overrides_service import (
    get_mapping_overrides_service,
)
from anibridge.app.web.services.mappings_query_spec import get_query_field_specs
from anibridge.app.web.services.mappings_service import get_mappings_service

__all__ = ["router"]


class MappingEdgeModel(PydanticMsgspecMixin, msgspec.Struct):
    target_provider: str
    target_entry_id: str
    source_range: str
    target_scope: str | None = None
    destination_range: str | None = None
    sources: list[str] = msgspec.field(default_factory=list)


class MappingItemModel(PydanticMsgspecMixin, msgspec.Struct):
    descriptor: str
    provider: str
    entry_id: str
    edges: list[MappingEdgeModel]
    scope: str | None = None
    custom: bool = False
    sources: list[str] = msgspec.field(default_factory=list)
    anilist: Media | None = None


class ListMappingsResponse(PydanticMsgspecMixin, msgspec.Struct):
    items: list[MappingItemModel]
    total: int
    page: int
    per_page: int
    pages: int
    with_anilist: bool = False


class DeleteMappingResponse(PydanticMsgspecMixin, msgspec.Struct):
    ok: bool


class RangeInputModel(PydanticMsgspecMixin, msgspec.Struct):
    source_range: str
    destination_range: str | None = None


class TargetInputModel(PydanticMsgspecMixin, msgspec.Struct):
    provider: str
    entry_id: str
    scope: str | None = None
    ranges: list[RangeInputModel] = msgspec.field(default_factory=list)
    deleted: bool = False


class MappingOverridePayload(PydanticMsgspecMixin, msgspec.Struct):
    """Payload for creating or updating a mapping override."""

    descriptor: str
    targets: list[TargetInputModel] = msgspec.field(default_factory=list)


class MappingRangeViewModel(PydanticMsgspecMixin, msgspec.Struct):
    source_range: str
    origin: str
    upstream: str | None = None
    custom: str | None = None
    effective: str | None = None
    inherited: bool = False


class MappingTargetViewModel(PydanticMsgspecMixin, msgspec.Struct):
    descriptor: str
    provider: str
    entry_id: str
    origin: str
    scope: str | None = None
    deleted: bool = False
    ranges: list[MappingRangeViewModel] = msgspec.field(default_factory=list)


class MappingLayersModel(PydanticMsgspecMixin, msgspec.Struct):
    upstream: dict[str, dict[str, str | None] | None] = msgspec.field(
        default_factory=dict
    )
    custom: dict[str, dict[str, str | None] | None] = msgspec.field(
        default_factory=dict
    )
    effective: dict[str, dict[str, str | None] | None] = msgspec.field(
        default_factory=dict
    )


class MappingDetailModel(PydanticMsgspecMixin, msgspec.Struct):
    descriptor: str
    provider: str
    entry_id: str
    scope: str | None = None
    layers: MappingLayersModel = msgspec.field(default_factory=MappingLayersModel)
    targets: list[MappingTargetViewModel] = msgspec.field(default_factory=list)


class FieldCapabilityModel(PydanticMsgspecMixin, msgspec.Struct):
    key: str
    type: str
    operators: list[str]
    aliases: list[str] = msgspec.field(default_factory=list)
    values: list[str] | None = None
    desc: str | None = None


class QueryCapabilitiesResponse(PydanticMsgspecMixin, msgspec.Struct):
    fields: list[FieldCapabilityModel]


router = APIRouter()


@router.get("", response_model=ListMappingsResponse)
async def list_mappings(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=250),
    q: str | None = None,
    custom_only: bool = False,
    with_anilist: bool = False,
) -> ListMappingsResponse:
    svc = get_mappings_service()

    async def cancel_check() -> bool:
        return await request.is_disconnected()

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
    except asyncio.CancelledError as exc:
        raise HTTPException(status_code=499, detail="Client Closed Request") from exc

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


@router.get("/query-capabilities", response_model=QueryCapabilitiesResponse)
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


@router.get("/{descriptor}", response_model=MappingDetailModel)
async def get_mapping(descriptor: str) -> MappingDetailModel:
    svc = get_mapping_overrides_service()
    data = await svc.get_mapping_detail(descriptor)
    return msgspec.convert(data, type=MappingDetailModel)


@router.post("", response_model=MappingDetailModel)
async def create_mapping(
    mapping: Annotated[MappingOverridePayload, Body()],
) -> MappingDetailModel:
    svc = get_mapping_overrides_service()
    data = await svc.save_override(
        descriptor=mapping.descriptor,
        targets=msgspec.to_builtins(mapping.targets),
    )
    return msgspec.convert(data, type=MappingDetailModel)


@router.put("/{descriptor}", response_model=MappingDetailModel)
async def update_mapping(
    descriptor: str,
    mapping: Annotated[MappingOverridePayload, Body()],
) -> MappingDetailModel:
    if mapping.descriptor != descriptor:
        raise MappingIdMismatchError("descriptor in path and body must match")

    svc = get_mapping_overrides_service()
    data = await svc.save_override(
        descriptor=mapping.descriptor,
        targets=msgspec.to_builtins(mapping.targets),
    )
    return msgspec.convert(data, type=MappingDetailModel)
