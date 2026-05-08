"""History API endpoints."""

import msgspec
from fastapi.param_functions import Query
from fastapi.routing import APIRouter

from anibridge.app.models.schemas._pydantic_msgspec import PydanticMsgspecMixin
from anibridge.app.web.services.history_service import (
    HistoryItem,
    HistoryPage,
    get_history_service,
)

router = APIRouter()

GetHistoryResponse = HistoryPage


class OkResponse(PydanticMsgspecMixin, msgspec.Struct):
    """Response model for successful operations."""

    ok: bool = True


class UndoResponse(PydanticMsgspecMixin, msgspec.Struct):
    """Response model for undo operation."""

    item: HistoryItem


class RetryResponse(PydanticMsgspecMixin, msgspec.Struct):
    """Response model for retry operation."""

    ok: bool = True


@router.get("/{profile}", response_model=GetHistoryResponse)
async def get_history(
    profile: str,
    limit: int = Query(25, ge=1, le=250),
    before_id: int | None = Query(
        None,
        ge=1,
        description="Return rows with id < before_id",
    ),
    after_id: int | None = Query(
        None,
        ge=1,
        description="Return rows with id > after_id",
    ),
    include_stats: bool = Query(True, description="Include grouped outcome stats"),
    outcome: str | None = Query(None, description="Filter by outcome"),
    library_namespace: str | None = Query(
        None, description="Filter by library provider namespace"
    ),
    list_namespace: str | None = Query(
        None, description="Filter by list provider namespace"
    ),
) -> GetHistoryResponse:
    """Get paginated timeline for profile.

    Args:
        profile (str): The profile name.
        limit (int): Maximum number of items to return.
        before_id (int | None): Cursor for loading older items.
        after_id (int | None): Cursor for loading newer items.
        include_stats (bool): Include grouped outcome stats when true.
        outcome (str | None): Filter by outcome.
        library_namespace (str | None): Filter by library provider namespace.
        list_namespace (str | None): Filter by list provider namespace.

    Returns:
        GetHistoryResponse: The paginated history response.

    Raises:
        SchedulerNotInitializedError: If the scheduler is not running.
        ProfileNotFoundError: If the profile is unknown.
    """
    return await get_history_service().get_page(
        profile=profile,
        limit=limit,
        before_id=before_id,
        after_id=after_id,
        outcome=outcome,
        library_namespace=library_namespace,
        list_namespace=list_namespace,
        include_stats=include_stats,
    )


@router.delete("/{profile}/{item_id}", response_model=OkResponse)
async def delete_history(profile: str, item_id: int) -> OkResponse:
    """Delete a history item.

    Args:
        profile (str): The profile name.
        item_id (int): The ID of the history item to delete.

    Returns:
        OkResponse: The response indicating success.

    Raises:
        HistoryItemNotFoundError: If the specified item does not exist.
    """
    await get_history_service().delete_item(profile, item_id)
    return OkResponse()


@router.post("/{profile}/{item_id}/undo", response_model=UndoResponse)
async def undo_history(profile: str, item_id: int) -> UndoResponse:
    """Undo a history item if possible.

    Args:
        profile (str): The profile name.
        item_id (int): The ID of the history item to undo.

    Returns:
        UndoResponse: The response containing the undone item.

    Raises:
        SchedulerNotInitializedError: If the scheduler is not running.
        ProfileNotFoundError: If the profile is unknown.
        HistoryItemNotFoundError: If the specified item does not exist.
    """
    item = await get_history_service().undo_item(profile, item_id)
    return UndoResponse(item=item)


@router.post("/{profile}/{item_id}/retry", response_model=RetryResponse)
async def retry_history(profile: str, item_id: int) -> RetryResponse:
    """Retry a failed or missing history item.

    Args:
        profile (str): The profile name.
        item_id (int): The ID of the history item to retry.

    Returns:
        RetryResponse: The response indicating success.

    Raises:
        SchedulerNotInitializedError: If the scheduler is not running.
        ProfileNotFoundError: If the profile is unknown.
        HistoryItemNotFoundError: If the specified item does not exist.
        HistoryPermissionError: If the user does not have permission to retry the item.
    """
    await get_history_service().retry_item(profile, item_id)
    return RetryResponse()
