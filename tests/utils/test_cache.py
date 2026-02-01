"""Tests for caching utilities."""

import aiocache
import pytest

from src.utils.cache import _generic_hash, lru_cache, ttl_cache


def test_generic_hash_order_insensitive_for_dicts():
    """Test that _generic_hash produces the same hash for dicts in different orders."""
    data_one = {"b": [1, 2], "a": {"x": 1}}
    data_two = {"a": {"x": 1}, "b": [1, 2]}

    assert _generic_hash(data_one) == _generic_hash(data_two)


def test_generic_hash_handles_cycles():
    """Test that _generic_hash can handle cyclic data structures."""
    cyclic = []
    cyclic.append(cyclic)

    result = _generic_hash(cyclic)

    assert isinstance(result, int)


def test_lru_cache_caches_unhashable_arguments():
    """Test that lru_cache caches results for unhashable arguments."""
    call_count = 0

    @lru_cache(maxsize=8)
    def compute(values):
        nonlocal call_count
        call_count += 1
        return sum(values)

    assert compute([1, 2, 3]) == 6
    assert compute([1, 2, 3]) == 6
    assert call_count == 1


def test_ttl_cache_caches_unhashable_arguments():
    """Test that ttl_cache caches results for unhashable arguments."""
    call_count = 0

    @ttl_cache(ttl=60)
    def compute(values):
        nonlocal call_count
        call_count += 1
        return sum(values)

    assert compute([4, 5]) == 9
    assert compute([4, 5]) == 9
    assert call_count == 1


@pytest.mark.asyncio
async def test_ttl_cache_caches_async_functions():
    """Test that ttl_cache caches async results with unhashable arguments."""
    call_count = 0

    @ttl_cache(ttl=60)
    async def fetch(value):
        nonlocal call_count
        call_count += 1
        return value

    assert await fetch(["a", "b"]) == ["a", "b"]
    assert await fetch(["a", "b"]) == ["a", "b"]
    assert call_count == 1

    aiocache.caches._caches.clear()
