"""Backup API endpoints."""

from typing import Annotated, Any

import msgspec
from litestar.handlers.http_handlers.decorators import get, post
from litestar.params import Body
from litestar.router import Router

from anibridge.app.web.services.backup_service import BackupMeta, get_backup_service

__all__ = ["router"]


class ListBackupsResponse(msgspec.Struct):
    """Response model for listing backups."""

    backups: Annotated[
        list[BackupMeta],
        msgspec.Meta(
            description="Available backup files for the requested profile.",
            examples=[[{"filename": "anibridge_default_anilist_20260508120000.json"}]],
        ),
    ]


class RestoreRequest(msgspec.Struct):
    """Request body for triggering a restore."""

    filename: Annotated[
        str,
        msgspec.Meta(
            min_length=1,
            description="Backup file name to restore for the selected profile.",
            examples=["anibridge_default_anilist_20260508120000.json"],
        ),
    ]


@get(path="/{profile:str}", sync_to_thread=True)
def list_backups(profile: str) -> ListBackupsResponse:
    """List backups for a profile.

    Args:
        profile (str): Profile name

    Returns:
        ListBackupsResponse: List of available backups

    Raises:
        SchedulerNotInitializedError: If the scheduler is not running.
        ProfileNotFoundError: If the profile is unknown.
    """
    backups = get_backup_service().list_backups(profile)
    return ListBackupsResponse(backups=backups)


@post(path="/{profile:str}/restore", status_code=200)
async def restore_backup(profile: str, data: Annotated[RestoreRequest, Body()]) -> None:
    """Restore a backup file (no dry-run mode).

    Raises:
        SchedulerNotInitializedError: If the scheduler is not running.
        ProfileNotFoundError: If the profile is unknown.
        InvalidBackupFilenameError: If the filename is invalid (e.g., path traversal).
        BackupFileNotFoundError: If the backup file does not exist.
        BackupParseError: If there was an error parsing or restoring the backup.
    """
    await get_backup_service().restore_backup(profile=profile, filename=data.filename)


@get(path="/{profile:str}/raw/{filename:str}", sync_to_thread=True)
def get_backup_raw(profile: str, filename: str) -> Any:
    """Return raw JSON content of a backup.

    The response is unvalidated JSON so the UI can present a preview.

    Raises:
        SchedulerNotInitializedError: If the scheduler is not running.
        ProfileNotFoundError: If the profile is unknown.
        InvalidBackupFilenameError: If the filename is invalid.
        BackupFileNotFoundError: If the backup file was not found.
    """
    return get_backup_service().read_backup_raw(profile, filename)


router = Router(
    path="/backups",
    route_handlers=[list_backups, restore_backup, get_backup_raw],
)
