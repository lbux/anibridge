"""Utilities for validating mapping range strings."""

import re
from dataclasses import dataclass

__all__ = [
    "SOURCE_RANGE_RE",
    "TARGET_RANGE_RE",
    "MappingRange",
    "is_valid_source_range",
    "is_valid_target_range",
    "mapping_weight",
    "parse_mapping_range",
    "parse_mapping_ranges",
    "parse_target_ranges",
    "ratio_to_weight",
]


SOURCE_RANGE_RE = re.compile(r"^\d+(?:-\d*)?(?:\|-?\d+)?$")
TARGET_RANGE_RE = re.compile(
    r"^\d+(?:-\d*)?(?:\|-?\d+)?(?:,\d+(?:-\d*)?(?:\|-?\d+)?)*$"
)


@dataclass(frozen=True, slots=True)
class MappingRange:
    """Normalized representation of a mapping range segment."""

    start: int
    end: int | None
    ratio: int | None = None

    def contains(self, value: int) -> bool:
        """Return True when the value is within this source range."""
        if value < self.start:
            return False
        return not (self.end is not None and value > self.end)


def is_valid_source_range(value: str) -> bool:
    """Return True if the value matches the source range schema."""
    return bool(SOURCE_RANGE_RE.match(value.strip()))


def is_valid_target_range(value: str) -> bool:
    """Return True if the value matches the target range schema."""
    return bool(TARGET_RANGE_RE.match(value.strip()))


def parse_mapping_range(value: str) -> MappingRange:
    """Parse a mapping range string into a `MappingRange` object."""
    raw = value.strip()
    if not is_valid_source_range(raw):
        raise ValueError(f"Invalid source range '{value}'")

    range_part, _, ratio_part = raw.partition("|")
    ratio = int(ratio_part) if ratio_part else None

    if "-" in range_part:
        start_str, end_str = range_part.split("-", 1)
        start = int(start_str)
        end = int(end_str) if end_str else None
    else:
        start = int(range_part)
        end = start

    return MappingRange(start=start, end=end, ratio=ratio)


def parse_mapping_ranges(
    values: list[str] | tuple[str, ...],
) -> tuple[MappingRange, ...]:
    """Parse multiple mapping range strings into `MappingRange` objects."""
    return tuple(parse_mapping_range(value) for value in values)


def parse_target_ranges(value: str) -> tuple[MappingRange, ...]:
    """Parse a target range string into one or more `MappingRange` segments."""
    raw = value.strip()
    if not is_valid_target_range(raw):
        raise ValueError(f"Invalid target range '{value}'")
    return tuple(parse_mapping_range(part) for part in raw.split(","))


def ratio_to_weight(ratio: int | None) -> float:
    """Convert a mapping ratio into weight in the opposing mapped range."""
    if ratio is None or ratio == 1:
        return 1.0
    if ratio > 0:
        return float(ratio)
    return 1.0 / abs(ratio)


def mapping_weight(
    source_range: MappingRange,
    target_ranges: tuple[MappingRange, ...],
) -> float:
    """Return source-unit weight in target units for a mapping segment."""
    if source_range.ratio is not None:
        return ratio_to_weight(source_range.ratio)

    if not target_ranges:
        return 1.0

    source_length = _range_length(source_range)
    target_length_total = 0
    has_open_ended_target = False
    target_ratio_weights: list[float] = []

    for target_range in target_ranges:
        source_per_target = ratio_to_weight(target_range.ratio)
        target_ratio_weights.append(source_per_target)
        target_length = _range_length(target_range)
        if target_length is None:
            has_open_ended_target = True
            continue
        target_length_total += target_length

    # If we have a closed range, we can calculate a precise weight
    if (
        source_length is not None
        and source_length > 0
        and not has_open_ended_target
        and target_length_total > 0
    ):
        return target_length_total / source_length

    # Open-ended ranges rely on ratio weights
    if target_ratio_weights and all(
        weight == target_ratio_weights[0] for weight in target_ratio_weights
    ):
        source_per_target = target_ratio_weights[0]
        if source_per_target == 0:
            return 1.0
        return 1.0 / source_per_target

    return 1.0


def _range_length(range_segment: MappingRange) -> int | None:
    """Return inclusive range length, or `None` for open-ended ranges."""
    if range_segment.end is None:
        return None
    return range_segment.end - range_segment.start + 1
