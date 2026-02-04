"""Caching decorators for LRU, TTL, and file-based caching. Supports async functions."""

import contextlib
import functools
import hashlib
import inspect
import pickle
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ParamSpec, Protocol, TypeVar, cast, overload

__all__ = ["CacheInfo", "cache", "file_cache", "lru_cache", "ttl_cache"]

P = ParamSpec("P")
T = TypeVar("T")


_DEFAULT_CACHE_DIR: Path | None = None


def _resolve_default_cache_dir() -> Path:
    """Resolve the default cache directory without eager settings import."""
    global _DEFAULT_CACHE_DIR
    if _DEFAULT_CACHE_DIR is None:
        from src.config.settings import get_config

        _DEFAULT_CACHE_DIR = get_config().data_path / ".cache"
    return _DEFAULT_CACHE_DIR


class CachedFunction(Protocol[P, T]):
    """Protocol for cached functions with cache management methods."""

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Call the cached function."""
        ...

    def cache_clear(self) -> None:
        """Clear the cache."""
        ...

    def cache_info(self) -> CacheInfo:
        """Get cache information."""
        ...


class CachedAsyncFunction(Protocol[P, T]):
    """Protocol for cached async functions with cache management methods."""

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[T]:
        """Call the cached async function."""
        ...

    def cache_clear(self) -> None:
        """Clear the cache."""
        ...

    def cache_info(self) -> CacheInfo:
        """Get cache information."""
        ...


@dataclass(frozen=True, slots=True)
class CacheInfo:
    """Cache statistics snapshot."""

    hits: int
    misses: int
    maxsize: int | None
    currsize: int
    ttl: float | None = None


def _generic_hash(obj: Any, _visited_ids: set[int] | None = None) -> int:
    """Generate a hash for arbitrary objects, handling unhashable types."""
    if _visited_ids is None:
        _visited_ids = set()

    obj_id = id(obj)
    if obj_id in _visited_ids:
        return hash("<cycle>")

    _visited_ids.add(obj_id)
    try:
        h = hash(obj)
    except TypeError:
        if isinstance(obj, list | tuple):
            h = hash(tuple(_generic_hash(item, _visited_ids) for item in obj))
        elif isinstance(obj, set):
            h = hash(frozenset(_generic_hash(item, _visited_ids) for item in obj))
        elif isinstance(obj, dict):
            h = hash(
                tuple(
                    sorted(
                        (_generic_hash(k, _visited_ids), _generic_hash(v, _visited_ids))
                        for k, v in obj.items()
                    )
                )
            )
        else:
            h = hash(obj_id)
    finally:
        # Use finally to ensure cleanup even if exception occurs
        _visited_ids.discard(obj_id)
    return h


def _make_key(
    args: tuple[Any, ...], kwargs: dict[str, Any], strict: bool = True
) -> int | tuple[Any, ...] | None:
    """Generate a cache key from args and kwargs. Supports unhashable types."""
    try:
        key = (args, tuple(sorted(kwargs.items())))
        hash(key)
        return key
    except TypeError:
        if strict is False:
            try:
                return _generic_hash((args, kwargs))
            except Exception:
                return None
        return None


class TTLCache:
    """Time-to-live cache implementation."""

    def __init__(self, ttl: float) -> None:
        """Initialize the TTL cache.

        Args:
            ttl (float): Time in seconds before cache entries expire.
        """
        self.ttl = ttl
        self.cache: dict[Any, Any] = {}
        self.timestamps: dict[Any, float] = {}
        self._lock = threading.RLock()

    def get(self, key: Any) -> Any:
        """Get value from cache if not expired.

        Args:
            key (Any): Key to retrieve.

        Returns:
            Any: Cached value.

        Raises:
            KeyError: If key is not in cache or has expired.
        """
        with self._lock:
            if key in self.cache:
                if time.time() - self.timestamps[key] < self.ttl:
                    return self.cache[key]
                # Expired - remove from cache
                del self.cache[key]
                del self.timestamps[key]
        raise KeyError(key)

    def set(self, key: Any, value: Any) -> None:
        """Store value in cache with current timestamp.

        Args:
            key (Any): Key to store.
            value (Any): Value to store.
        """
        with self._lock:
            self.cache[key] = value
            self.timestamps[key] = time.time()

    def clear(self) -> None:
        """Clear all cached items."""
        with self._lock:
            self.cache.clear()
            self.timestamps.clear()

    def size(self) -> int:
        """Return the current cache size."""
        with self._lock:
            return len(self.cache)


@overload
def ttl_cache(
    ttl: float = 300, *, key: Callable[..., Any] | None = None
) -> Callable[[Callable[P, T]], CachedFunction[P, T]]: ...


@overload
def ttl_cache(
    ttl: float = 300, *, key: Callable[..., Any] | None = None
) -> Callable[[Callable[P, Awaitable[T]]], CachedAsyncFunction[P, T]]: ...


def ttl_cache(
    ttl: float = 300, *, key: Callable[..., Any] | None = None
) -> Callable[
    [Callable[P, T] | Callable[P, Awaitable[T]]],
    CachedFunction[P, T] | CachedAsyncFunction[P, T],
]:
    """Decorator that caches function results with a time-to-live.

    Args:
        ttl (float): Time in seconds before cache expires (default: 300)
        key (Callable | None): Optional function to generate cache key from args/kwargs.
            Should accept the same arguments as the decorated function and return a
            hashable key.

    Returns:
        Decorator: Decorated function with TTL-based caching

    Example:
        @ttl_cache(ttl=60)
        def expensive_function(x):
            return x ** 2

        @ttl_cache(ttl=120, key=lambda x, y: (x, y))
        async def async_expensive_function(x, y):
            await asyncio.sleep(1)
            return x + y
    """

    def decorator(
        func: Callable[P, T] | Callable[P, Awaitable[T]],
    ) -> CachedFunction[P, T] | CachedAsyncFunction[P, T]:
        """Inner decorator function."""
        cache = TTLCache(ttl)
        stats_lock = threading.RLock()
        is_async = inspect.iscoroutinefunction(func)

        def cache_clear() -> None:
            cache.clear()

        hits = 0
        misses = 0

        def cache_info() -> CacheInfo:
            with stats_lock:
                hits_snapshot = hits
                misses_snapshot = misses
            return CacheInfo(
                hits=hits_snapshot,
                misses=misses_snapshot,
                maxsize=None,
                currsize=cache.size(),
                ttl=ttl,
            )

        def get_cache_key(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
            """Generate cache key using custom function or default."""
            if key is not None:
                try:
                    return key(*args, **kwargs)
                except Exception:
                    return None
            return _make_key(args, kwargs, strict=False)

        if is_async:

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                nonlocal hits, misses
                cache_key = get_cache_key(args, kwargs)
                if cache_key is None:
                    result = func(*args, **kwargs)
                    return await cast(Awaitable[T], result)

                try:
                    cached = cache.get(cache_key)
                    with stats_lock:
                        hits += 1
                    return cast(T, cached)
                except KeyError:
                    with stats_lock:
                        misses += 1
                    result = func(*args, **kwargs)
                    awaited_result = await cast(Awaitable[T], result)
                    cache.set(cache_key, awaited_result)
                    return awaited_result

            async_wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
            async_wrapper.cache_info = cache_info  # type: ignore[attr-defined]
            return cast(CachedAsyncFunction[P, T], async_wrapper)

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            nonlocal hits, misses
            cache_key = get_cache_key(args, kwargs)
            if cache_key is None:
                return cast(T, func(*args, **kwargs))

            try:
                cached = cache.get(cache_key)
                with stats_lock:
                    hits += 1
                return cast(T, cached)
            except KeyError:
                with stats_lock:
                    misses += 1
                result = cast(T, func(*args, **kwargs))
                cache.set(cache_key, result)
                return result

        sync_wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
        sync_wrapper.cache_info = cache_info  # type: ignore[attr-defined]
        return cast(CachedFunction[P, T], sync_wrapper)

    return decorator


@overload
def lru_cache(
    maxsize: int = 128, *, key: Callable[..., Any] | None = None
) -> Callable[[Callable[P, T]], CachedFunction[P, T]]: ...


@overload
def lru_cache(
    maxsize: int = 128, *, key: Callable[..., Any] | None = None
) -> Callable[[Callable[P, Awaitable[T]]], CachedAsyncFunction[P, T]]: ...


def lru_cache(
    maxsize: int = 128, *, key: Callable[..., Any] | None = None
) -> Callable[
    [Callable[P, T] | Callable[P, Awaitable[T]]],
    CachedFunction[P, T] | CachedAsyncFunction[P, T],
]:
    """LRU cache decorator for both sync and async functions.

    Args:
        maxsize (int): Maximum number of cached items.
        key (Callable | None): Optional function to generate cache key from args/kwargs.
            Should accept the same arguments as the decorated function and return a
            hashable key.

    Returns:
        Decorator: Decorated function with LRU caching.

    Example:
        @lru_cache(maxsize=256)
        async def fetch_data(url):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    return await response.text()

        # Custom key that only considers the first argument
        @lru_cache(maxsize=100, key=lambda user_id, include_details=False: user_id)
        async def get_user(user_id, include_details=False):
            return await fetch_user_data(user_id, include_details)

        # Works with sync functions too
        @lru_cache(maxsize=50, key=lambda x, y, z=None: (x, y))
        def compute(x, y, z=None):
            return x + y
    """

    def decorator(
        func: Callable[P, T] | Callable[P, Awaitable[T]],
    ) -> CachedFunction[P, T] | CachedAsyncFunction[P, T]:
        """Inner decorator function."""
        cache: dict[Any, Any] = {}
        access_order: list[Any] = []
        cache_lock = threading.RLock()
        is_async = inspect.iscoroutinefunction(func)

        def get_cache_key(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
            """Generate cache key using custom function or default."""
            if key is not None:
                try:
                    return key(*args, **kwargs)
                except Exception:
                    return None
            else:
                return _make_key(args, kwargs, strict=False)

        if is_async:
            hits = 0
            misses = 0

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                nonlocal cache, access_order, hits, misses

                cache_key = get_cache_key(args, kwargs)
                if cache_key is None:
                    result = func(*args, **kwargs)
                    return await cast(Awaitable[T], result)

                with cache_lock:
                    if cache_key in cache:
                        # Move to end (most recently used)
                        if cache_key in access_order:
                            access_order.remove(cache_key)
                        access_order.append(cache_key)
                        hits += 1
                        return cache[cache_key]

                    misses += 1

                result = func(*args, **kwargs)
                awaited_result = await cast(Awaitable[T], result)

                with cache_lock:
                    if cache_key in cache:
                        if cache_key in access_order:
                            access_order.remove(cache_key)
                        access_order.append(cache_key)
                        return cache[cache_key]

                    cache[cache_key] = awaited_result
                    access_order.append(cache_key)

                    # Remove oldest if exceeding maxsize
                    if maxsize is not None and len(cache) > maxsize:
                        oldest = access_order.pop(0)
                        del cache[oldest]

                return awaited_result

            def cache_clear() -> None:
                nonlocal cache, access_order
                with cache_lock:
                    cache.clear()
                    access_order.clear()

            def cache_info() -> CacheInfo:
                with cache_lock:
                    hits_snapshot = hits
                    misses_snapshot = misses
                    currsize = len(cache)
                return CacheInfo(
                    hits=hits_snapshot,
                    misses=misses_snapshot,
                    maxsize=maxsize,
                    currsize=currsize,
                )

            async_wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
            async_wrapper.cache_info = cache_info  # type: ignore[attr-defined]
            return cast(CachedAsyncFunction[P, T], async_wrapper)
        else:
            hits = 0
            misses = 0

            @functools.wraps(func)
            def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                nonlocal cache, access_order, hits, misses

                cache_key = get_cache_key(args, kwargs)
                if cache_key is None:
                    return cast(T, func(*args, **kwargs))

                with cache_lock:
                    if cache_key in cache:
                        # Move to end (most recently used)
                        if cache_key in access_order:
                            access_order.remove(cache_key)
                        access_order.append(cache_key)
                        hits += 1
                        return cache[cache_key]

                    misses += 1

                result = cast(T, func(*args, **kwargs))

                with cache_lock:
                    if cache_key in cache:
                        if cache_key in access_order:
                            access_order.remove(cache_key)
                        access_order.append(cache_key)
                        return cache[cache_key]

                    cache[cache_key] = result
                    access_order.append(cache_key)

                    # Remove oldest if exceeding maxsize
                    if maxsize is not None and len(cache) > maxsize:
                        oldest = access_order.pop(0)
                        del cache[oldest]

                return result

            def cache_clear() -> None:
                nonlocal cache, access_order
                with cache_lock:
                    cache.clear()
                    access_order.clear()

            def cache_info() -> CacheInfo:
                with cache_lock:
                    hits_snapshot = hits
                    misses_snapshot = misses
                    currsize = len(cache)
                return CacheInfo(
                    hits=hits_snapshot,
                    misses=misses_snapshot,
                    maxsize=maxsize,
                    currsize=currsize,
                )

            sync_wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
            sync_wrapper.cache_info = cache_info  # type: ignore[attr-defined]
            return cast(CachedFunction[P, T], sync_wrapper)

    return decorator


@overload
def file_cache(
    cache_dir: str | Path | None = None,
    ttl: float | None = None,
    *,
    key: Callable[..., Any] | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], CachedAsyncFunction[P, T]]: ...


@overload
def file_cache(
    cache_dir: str | Path | None = None,
    ttl: float | None = None,
    *,
    key: Callable[..., Any] | None = None,
) -> Callable[[Callable[P, T]], CachedFunction[P, T]]: ...


def file_cache(
    cache_dir: str | Path | None = None,
    ttl: float | None = None,
    *,
    key: Callable[..., Any] | None = None,
) -> Callable[
    [Callable[P, T] | Callable[P, Awaitable[T]]],
    CachedFunction[P, T] | CachedAsyncFunction[P, T],
]:
    """Decorator that caches function results to disk using pickle.

    Args:
        cache_dir (str | Path): Directory to store cache files (default: ".cache")
        ttl (float | None): Optional time-to-live in seconds (None = no expiration)
        key (Callable | None): Optional function to generate cache key from args/kwargs.
            Should accept the same arguments as the decorated function and return a
            hashable key.

    Returns:
        Decorator: Decorated function with file-based caching

    Example:
        @file_cache(cache_dir="./my_cache", ttl=3600)
        def process_large_dataset(data_path):
            # Expensive computation
            return result

        @file_cache(ttl=600, key=lambda endpoint, **kwargs: endpoint)
        async def fetch_api_data(endpoint, **kwargs):
            # API call - cache only based on endpoint, ignore other params
            return data

        # Cache based on specific parameters only
        @file_cache(cache_dir="./cache", key=lambda x, y, z=None: (x, y))
        def compute(x, y, z=None):
            # z is not part of the cache key
            return x + y
    """
    if cache_dir is None:
        resolved_cache_dir = _resolve_default_cache_dir()
    else:
        resolved_cache_dir = Path(cache_dir)

    def decorator(
        func: Callable[P, T] | Callable[P, Awaitable[T]],
    ) -> CachedFunction[P, T] | CachedAsyncFunction[P, T]:
        """Inner decorator function."""
        func_name = str(getattr(func, "__name__", "unknown_function"))
        (resolved_cache_dir / func_name).mkdir(parents=True, exist_ok=True)
        stats_lock = threading.RLock()
        is_async = inspect.iscoroutinefunction(func)
        hits = 0
        misses = 0

        def get_cache_path(cache_key: Any) -> Path:
            """Generate a cache file path based on the function name and arguments."""
            try:
                key_str = str(cache_key)
            except Exception:
                key_str = repr(cache_key)
            key_hash = hashlib.md5(key_str.encode()).hexdigest()
            return resolved_cache_dir / func_name / f"{func_name}_{key_hash}.cache"

        def load_from_cache(cache_path: Path) -> tuple[bool, Any]:
            """Load cached value if valid. Returns (success, value)."""
            if cache_path.exists() and (
                ttl is None or (time.time() - cache_path.stat().st_mtime < ttl)
            ):
                try:
                    with open(cache_path, "rb") as f:
                        return True, pickle.load(f)
                except (pickle.PickleError, EOFError, Exception):
                    pass
            return False, None

        def save_to_cache(cache_path: Path, result: Any) -> None:
            """Save result to cache file."""
            try:
                with cache_path.open("wb") as f:
                    pickle.dump(result, f)
            except (pickle.PickleError, TypeError, Exception):
                pass  # Can't pickle result - don't cache

        def cache_clear() -> None:
            """Clear all cache files for this function."""
            try:
                func_cache_dir = resolved_cache_dir / func_name
                with stats_lock:
                    for filename in func_cache_dir.iterdir():
                        if filename.name.endswith(".cache"):
                            filename.unlink()
                    with contextlib.suppress(OSError):
                        func_cache_dir.rmdir()
            except FileNotFoundError:
                pass

        def cache_info() -> CacheInfo:
            with stats_lock:
                hits_snapshot = hits
                misses_snapshot = misses
                func_cache_dir = resolved_cache_dir / func_name
                with contextlib.suppress(FileNotFoundError):
                    currsize = sum(
                        1
                        for filename in func_cache_dir.iterdir()
                        if filename.name.endswith(".cache")
                    )
                    return CacheInfo(
                        hits=hits_snapshot,
                        misses=misses_snapshot,
                        maxsize=None,
                        currsize=currsize,
                        ttl=ttl,
                    )
            return CacheInfo(
                hits=hits_snapshot,
                misses=misses_snapshot,
                maxsize=None,
                currsize=0,
                ttl=ttl,
            )

        def get_cache_key(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
            """Generate cache key using custom function or default."""
            if key is not None:
                try:
                    return key(*args, **kwargs)
                except Exception:
                    return None
            return _make_key(args, kwargs, strict=False)

        if is_async:

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                nonlocal hits, misses
                cache_key = get_cache_key(args, kwargs)
                if cache_key is None:
                    result = func(*args, **kwargs)
                    return await cast(Awaitable[T], result)

                cache_path = get_cache_path(cache_key)
                with stats_lock:
                    success, cached_value = load_from_cache(cache_path)
                if success:
                    with stats_lock:
                        hits += 1
                    return cast(T, cached_value)

                with stats_lock:
                    misses += 1
                result = func(*args, **kwargs)
                awaited_result = await cast(Awaitable[T], result)
                with stats_lock:
                    save_to_cache(cache_path, awaited_result)
                return awaited_result

            async_wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
            async_wrapper.cache_info = cache_info  # type: ignore[attr-defined]
            return cast(CachedAsyncFunction[P, T], async_wrapper)

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            nonlocal hits, misses
            cache_key = get_cache_key(args, kwargs)
            if cache_key is None:
                return cast(T, func(*args, **kwargs))

            cache_path = get_cache_path(cache_key)
            with stats_lock:
                success, cached_value = load_from_cache(cache_path)
            if success:
                with stats_lock:
                    hits += 1
                return cast(T, cached_value)

            with stats_lock:
                misses += 1
            result = cast(T, func(*args, **kwargs))
            with stats_lock:
                save_to_cache(cache_path, result)
            return result

        sync_wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
        sync_wrapper.cache_info = cache_info  # type: ignore[attr-defined]
        return cast(CachedFunction[P, T], sync_wrapper)

    return decorator


@overload
def cache[**P, T](
    func: Callable[P, T],
) -> CachedFunction[P, T]: ...


@overload
def cache[**P, T](
    func: Callable[P, Awaitable[T]],
) -> CachedAsyncFunction[P, T]: ...


def cache(
    func: Callable[P, T] | Callable[P, Awaitable[T]],
) -> CachedFunction[P, T] | CachedAsyncFunction[P, T]:
    """Generic cache decorator that applies an LRU cache with cache size of 1.

    Args:
        func (Callable): Function to be cached.

    Returns:
        Decorator: Decorated function with LRU caching.

    Example:
        @cache
        def compute_square(x):
            return x * x

        @cache
        async def fetch_data(url):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    return await response.text()
    """
    return lru_cache(maxsize=1)(func)
