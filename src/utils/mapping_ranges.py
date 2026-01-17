"""Utilities for validating mapping range strings."""

from __future__ import annotations

import re

__all__ = [
    "SOURCE_RANGE_RE",
    "TARGET_RANGE_RE",
    "is_valid_source_range",
    "is_valid_target_range",
]


SOURCE_RANGE_RE = re.compile(r"^\d+(?:-\d*)?(?:\|-?\d+)?$")
TARGET_RANGE_RE = re.compile(
    r"^\d+(?:-\d*)?(?:\|-?\d+)?(?:,\d+(?:-\d*)?(?:\|-?\d+)?)*$"
)


def is_valid_source_range(value: str) -> bool:
    """Return True if the value matches the source range schema."""
    return bool(SOURCE_RANGE_RE.match(value.strip()))


def is_valid_target_range(value: str) -> bool:
    """Return True if the value matches the target range schema."""
    return bool(TARGET_RANGE_RE.match(value.strip()))
