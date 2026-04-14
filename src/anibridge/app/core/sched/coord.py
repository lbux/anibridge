"""Global scheduling coordination primitives."""

import asyncio
from collections.abc import Awaitable, Callable


class GlobalSyncCoordinator:
    """Serialize maintenance with profile sync activity."""

    def __init__(self) -> None:
        """Initialize coordinator counters and synchronization state."""
        self._active_profile_syncs = 0
        self._maintenance_active = False
        self._maintenance_waiting = 0
        self._changed = asyncio.Event()

    def _notify(self) -> None:
        self._changed.set()

    async def _wait_for(self, predicate: Callable[[], bool]) -> None:
        while not predicate():
            self._changed.clear()
            if not predicate():
                await self._changed.wait()

    async def acquire_profile_slot(self, _profile_name: str) -> None:
        """Block profile sync starts while maintenance is active or pending."""
        await self._wait_for(
            lambda: not self._maintenance_active and self._maintenance_waiting == 0
        )
        self._active_profile_syncs += 1

    def release_profile_slot(self, _profile_name: str) -> None:
        """Release an active profile sync slot."""
        self._active_profile_syncs = max(0, self._active_profile_syncs - 1)
        self._notify()

    async def run_maintenance(self, work: Callable[[], Awaitable[None]]) -> None:
        """Execute maintenance work with exclusive access against profile syncs."""
        self._maintenance_waiting += 1
        try:
            await self._wait_for(
                lambda: not self._maintenance_active and self._active_profile_syncs == 0
            )
        except BaseException:
            self._maintenance_waiting -= 1
            self._notify()
            raise

        self._maintenance_waiting -= 1
        self._maintenance_active = True

        try:
            await work()
        finally:
            self._maintenance_active = False
            self._notify()

    def get_metrics(self) -> dict[str, int | bool]:
        """Expose coordinator counters for diagnostics."""
        return {
            "active_profile_syncs": self._active_profile_syncs,
            "maintenance_active": self._maintenance_active,
            "maintenance_waiting": self._maintenance_waiting,
        }
