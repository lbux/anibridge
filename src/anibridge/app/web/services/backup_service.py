"""Backup listing and restore service."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson
from anibridge.utils.cache import cache
from pydantic import BaseModel

from anibridge.app import log
from anibridge.app.exceptions import (
    BackupFileNotFoundError,
    BackupParseError,
    InvalidBackupFilenameError,
    ProfileNotFoundError,
    SchedulerNotInitializedError,
    SchedulerUnavailableError,
)
from anibridge.app.web.state import get_app_state

__all__ = ["BackupService", "get_backup_service"]


class BackupMeta(BaseModel):
    """Metadata about a backup file used for listing in the UI."""

    filename: str
    created_at: datetime
    size_bytes: int
    entries: int | None = None
    user: str | None = None
    age_seconds: float


class BackupService:
    """Service for listing and restoring provider-managed backups."""

    def list_backups(self, profile: str) -> list[BackupMeta]:
        """Enumerate available backups for a profile.

        Args:
            profile: Profile name.

        Returns:
            list[BackupMeta]: List of backup metadata, newest first.

        Raises:
            SchedulerNotInitializedError: If the scheduler is not running.
            ProfileNotFoundError: If the profile is unknown.
        """
        scheduler = get_app_state().scheduler
        if not scheduler:
            raise SchedulerNotInitializedError("Scheduler not available")
        profile_config = scheduler.global_config.profiles.get(profile)
        if profile_config is None:
            raise ProfileNotFoundError(f"Unknown profile: {profile}")

        log.debug("Listing backups for profile $$'%s'$$", profile)
        bdir = scheduler.global_config.data_path / "backups" / profile
        if not bdir.exists():
            log.debug("Backup directory $$'%s'$$ does not exist", bdir)
            return []
        metas: list[BackupMeta] = []
        now = datetime.now(UTC)

        bridge = scheduler.bridge_clients.get(profile)
        list_provider = bridge.list_provider if bridge is not None else None
        provider_user = list_provider.user() if list_provider is not None else None

        count = 0
        provider_namespace = (
            list_provider.NAMESPACE if list_provider is not None else None
        )
        pattern = (
            f"anibridge_{profile}_{provider_namespace}_*.json"
            if provider_namespace
            else f"anibridge_{profile}_{profile_config.list_provider}_*.json"
        )
        if scheduler.failed_profile_errors.get(profile):
            pattern = f"anibridge_{profile}_*.json"
        for f in sorted(bdir.glob(pattern)):
            try:
                parts = f.name.split(".")
                ts_raw = parts[-2] if len(parts) >= 2 else None
                dt: datetime | None = None
                if ts_raw and ts_raw.isdigit():
                    try:
                        dt = datetime.strptime(ts_raw, "%Y%m%d%H%M%S").replace(
                            tzinfo=UTC
                        )
                    except ValueError:
                        dt = datetime.fromtimestamp(f.stat().st_mtime, UTC)
                else:
                    dt = datetime.fromtimestamp(f.stat().st_mtime, UTC)
                metas.append(
                    BackupMeta(
                        filename=f.name,
                        created_at=dt,
                        size_bytes=f.stat().st_size,
                        entries=None,  # Can be populated on demand
                        user=provider_user.title if provider_user else None,
                        age_seconds=(now - dt).total_seconds(),
                    )
                )
                count += 1
            except Exception:
                continue
        log.debug(
            "Found %s backups for profile $$'%s'$$",
            count,
            profile,
        )
        return list(reversed(metas))  # Newest first

    def read_backup_raw(self, profile: str, filename: str) -> Any:
        """Return the raw JSON content of a backup file.

        Args:
            profile: Profile name
            filename: Backup filename (basename only)

        Returns:
            Any: Parsed JSON content.

        Raises:
            SchedulerNotInitializedError: If the scheduler is not running.
            ProfileNotFoundError: If the profile is unknown.
            InvalidBackupFilenameError: If the filename is invalid.
            BackupFileNotFoundError: If the file does not exist.
        """
        scheduler = get_app_state().scheduler
        if not scheduler:
            raise SchedulerNotInitializedError("Scheduler not available")
        if profile not in scheduler.global_config.profiles:
            raise ProfileNotFoundError(f"Unknown profile: {profile}")

        log.debug(
            "Reading raw backup $$'%s'$$ for profile $$'%s'$$",
            filename,
            profile,
        )
        bdir = scheduler.global_config.data_path / "backups" / profile
        path = self._resolve_backup_path(bdir, filename)

        return orjson.loads(path.read_bytes())

    def _resolve_backup_path(self, bdir: Path, filename: str) -> Path:
        """Resolve and validate a backup filename for a profile."""
        path = (bdir / filename).resolve()

        if path.parent != bdir.resolve():
            raise InvalidBackupFilenameError("Invalid backup filename")
        if not path.exists():
            raise BackupFileNotFoundError("Backup file not found")

        return path

    async def restore_backup(self, profile: str, filename: str) -> None:
        """Restore a backup file for a profile.

        Args:
            profile: Profile name
            filename: Backup filename (basename only)

        Raises:
            SchedulerNotInitializedError: If the scheduler is not running.
            ProfileNotFoundError: If the profile is unknown.
            SchedulerUnavailableError: If the profile failed initialization.
            InvalidBackupFilenameError: If the filename is invalid.
            BackupFileNotFoundError: If the file does not exist.
            BackupParseError: If there was an error parsing or restoring the backup.
        """
        scheduler = get_app_state().scheduler
        if not scheduler:
            raise SchedulerNotInitializedError("Scheduler not available")
        if profile not in scheduler.global_config.profiles:
            raise ProfileNotFoundError(f"Unknown profile: {profile}")
        init_error = scheduler.failed_profile_errors.get(profile)
        if init_error:
            raise SchedulerUnavailableError(
                f"Profile '{profile}' is unavailable: {init_error}"
            )

        log.info(
            "Restoring backup $$'%s'$$ for profile $$'%s'$$",
            filename,
            profile,
        )
        bridge = scheduler.bridge_clients.get(profile)
        if bridge is None:
            raise SchedulerUnavailableError(
                f"Profile '{profile}' is unavailable for restore"
            )
        bdir = scheduler.global_config.data_path / "backups" / profile
        path = self._resolve_backup_path(bdir, filename)

        raw_backup = path.read_text(encoding="utf-8")
        try:
            await bridge.list_provider.restore_list(raw_backup)
        except NotImplementedError as exc:
            raise BackupParseError(
                "List provider does not support backup restoration"
            ) from exc
        except Exception as exc:
            raise BackupParseError(f"Error during backup restoration: {exc}") from exc
        log.info(
            "Successfully restored backup $$'%s'$$ for profile $$'%s'$$",
            filename,
            profile,
        )


@cache
def get_backup_service() -> BackupService:
    """Get the singleton BackupService instance.

    Returns:
        BackupService: The singleton BackupService instance.
    """
    return BackupService()
