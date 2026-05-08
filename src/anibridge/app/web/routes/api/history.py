"""History API endpoints."""

import msgspec
from litestar.handlers.http_handlers.decorators import delete, get, post
from litestar.router import Router

from anibridge.app.web.services.history_service import (
    HistoryItem,
    HistoryPage,
    get_history_service,
)

__all__ = ["router"]

GetHistoryResponse = HistoryPage


class OkResponse(msgspec.Struct):
    """Response model for successful operations."""

    ok: bool = True


class UndoResponse(msgspec.Struct):
    """Response model for undo operation."""

    item: HistoryItem


class RetryResponse(msgspec.Struct):
    """Response model for retry operation."""

    ok: bool = True


@get(path="/{profile:str}")
async def get_history(
    profile: str,
    limit: int = 25,
    before_id: int | None = None,
    after_id: int | None = None,
    include_stats: bool = True,
    outcome: str | None = None,
    library_namespace: str | None = None,
    list_namespace: str | None = None,
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


@delete(path="/{profile:str}/{item_id:int}", status_code=200)
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


@post(path="/{profile:str}/{item_id:int}/undo", status_code=200)
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


@post(path="/{profile:str}/{item_id:int}/retry", status_code=200)
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


router = Router(
    path="/history",
    route_handlers=[get_history, delete_history, undo_history, retry_history],
)
