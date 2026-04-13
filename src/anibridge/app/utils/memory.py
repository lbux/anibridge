"""Memory management utilities."""

import ctypes
import ctypes.util
import gc
import sys

__all__ = ["release_memory"]

_libc_name = ctypes.util.find_library("c")
_libc = ctypes.CDLL(_libc_name) if _libc_name else None


def release_memory() -> None:
    """Run garbage collection and return freed pages to the OS.

    Calls `gc.collect()` followed by `malloc_trim(0)` on glibc-based systems so that
    the C allocator returns unused pages to the kernel. On non-glibc platforms the
    `gc.collect()` call still runs.
    """
    gc.collect()
    if _libc is not None and sys.platform == "linux":
        _libc.malloc_trim(0)
