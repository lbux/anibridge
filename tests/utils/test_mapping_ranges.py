"""Tests for mapping range helpers."""

import pytest

from anibridge.app.utils.mapping_ranges import (
    MappingRange,
    is_valid_source_range,
    is_valid_target_range,
    parse_mapping_range,
    parse_mapping_ranges,
    parse_target_ranges,
    ratio_to_weight,
)


def test_is_valid_source_range_accepts_and_rejects() -> None:
    """Source range validation should accept valid patterns."""
    assert is_valid_source_range("1")
    assert is_valid_source_range("1-12")
    assert is_valid_source_range("1-")
    assert is_valid_source_range("1|2")
    assert not is_valid_source_range("a")


def test_is_valid_target_range_accepts_and_rejects() -> None:
    """Target range validation should accept comma-separated values."""
    assert is_valid_target_range("1")
    assert is_valid_target_range("1-12")
    assert is_valid_target_range("1-12,13")
    assert is_valid_target_range("1|2,3|1")
    assert not is_valid_target_range("1,,2")


def test_parse_source_range_parses_ranges() -> None:
    """Parsing should return correct start/end/ratio values."""
    parsed = parse_mapping_range("1-3|2")

    assert parsed == MappingRange(start=1, end=3, ratio=2)
    assert parsed.contains(2) is True
    assert parsed.contains(4) is False


def test_parse_source_range_open_end() -> None:
    """Open-ended ranges should yield None for end."""
    parsed = parse_mapping_range("5-")
    assert parsed.start == 5
    assert parsed.end is None


def test_parse_source_range_rejects_invalid() -> None:
    """Invalid ranges should raise a ValueError."""
    with pytest.raises(ValueError):
        parse_mapping_range("bad")


def test_parse_source_ranges_parses_list() -> None:
    """Parsing a list should return a tuple of MappingRange values."""
    parsed = parse_mapping_ranges(["1", "2-3"])

    assert len(parsed) == 2
    assert parsed[0].start == 1
    assert parsed[1].end == 3


def test_parse_target_ranges_parses_multiple_segments() -> None:
    """Target ranges should parse comma-separated segments and ratios."""
    parsed = parse_target_ranges("1-6,8-13|2")

    assert parsed == (
        MappingRange(start=1, end=6, ratio=None),
        MappingRange(start=8, end=13, ratio=2),
    )


def test_parse_target_ranges_rejects_invalid() -> None:
    """Invalid target range strings should raise ValueError."""
    with pytest.raises(ValueError):
        parse_target_ranges("1,,2")


def test_ratio_to_weight_supports_positive_and_negative() -> None:
    """Ratio conversion should preserve existing source ratio semantics."""
    assert ratio_to_weight(None) == 1.0
    assert ratio_to_weight(1) == 1.0
    assert ratio_to_weight(2) == 2.0
    assert ratio_to_weight(-2) == 0.5
