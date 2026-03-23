"""Tests for mapping range helpers."""

import pytest

from anibridge.app.utils.mapping_ranges import (
    MappingRange,
    is_valid_source_range,
    is_valid_target_range,
    mapping_weight_plan,
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
    assert is_valid_source_range("1|0")
    assert not is_valid_source_range("a")


def test_is_valid_target_range_accepts_and_rejects() -> None:
    """Target range validation should accept comma-separated values."""
    assert is_valid_target_range("1")
    assert is_valid_target_range("1-12")
    assert is_valid_target_range("1-12,13")
    assert is_valid_target_range("1|2,3|1")
    assert is_valid_target_range("1|0,2")
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


def test_mapping_weight_plan_builds_segmented_weights() -> None:
    """Weight plans should align source indexes to target segment semantics."""
    source = MappingRange(start=1, end=23, ratio=None)
    targets = (
        MappingRange(start=1, end=4, ratio=None),
        MappingRange(start=5, end=6, ratio=-2),
        MappingRange(start=7, end=9, ratio=None),
        MappingRange(start=10, end=11, ratio=-2),
        MappingRange(start=12, end=14, ratio=None),
        MappingRange(start=15, end=16, ratio=-2),
        MappingRange(start=17, end=26, ratio=None),
    )

    plan = mapping_weight_plan(source, targets)
    assert plan.default_weight == pytest.approx(26 / 23)
    assert plan.per_index_weights is not None

    weights = plan.per_index_weights
    assert weights[4] == 1.0
    assert weights[5] == 2.0
    assert weights[9] == 2.0
    assert weights[13] == 2.0
    assert weights[14] == 1.0
    assert weights[23] == 1.0


def test_mapping_weight_plan_uses_aggregate_for_open_ended_segment() -> None:
    """Open-ended segments should rely on aggregate weighting behavior."""
    source = MappingRange(start=1, end=10, ratio=None)
    targets = (MappingRange(start=1, end=None, ratio=None),)

    plan = mapping_weight_plan(source, targets)
    assert plan.default_weight == 1.0
    assert plan.per_index_weights is None


def test_mapping_weight_plan_omits_uniform_per_index_map() -> None:
    """Uniform segmented mappings should keep a scalar weight plan."""
    source = MappingRange(start=1, end=2, ratio=None)
    targets = (
        MappingRange(start=10, end=10, ratio=None),
        MappingRange(start=20, end=20, ratio=None),
    )

    plan = mapping_weight_plan(source, targets)

    assert plan.default_weight == 1.0
    assert plan.per_index_weights is None


def test_mapping_weight_plan_prefers_explicit_source_ratio() -> None:
    """Explicit source ratio should override target-side segment heuristics."""
    source = MappingRange(start=1, end=4, ratio=-2)
    targets = (
        MappingRange(start=1, end=4, ratio=None),
        MappingRange(start=5, end=8, ratio=None),
    )

    plan = mapping_weight_plan(source, targets)

    assert plan.default_weight == 0.5
    assert plan.per_index_weights is None


def test_mapping_weight_plan_weight_for_uses_default_outside_piecewise_map() -> None:
    """weight_for should fall back to the aggregate default for missing indexes."""
    source = MappingRange(start=1, end=23, ratio=None)
    targets = (
        MappingRange(start=1, end=4, ratio=None),
        MappingRange(start=5, end=6, ratio=-2),
        MappingRange(start=7, end=9, ratio=None),
        MappingRange(start=10, end=11, ratio=-2),
        MappingRange(start=12, end=14, ratio=None),
        MappingRange(start=15, end=16, ratio=-2),
        MappingRange(start=17, end=26, ratio=None),
    )

    plan = mapping_weight_plan(source, targets)

    assert plan.per_index_weights is not None
    assert plan.weight_for(5) == 2.0
    assert plan.weight_for(999) == pytest.approx(26 / 23)


def test_ratio_to_weight_supports_zero_as_empty() -> None:
    """A zero ratio should represent an explicitly empty mapping contribution."""
    assert ratio_to_weight(0) == 0.0


def test_mapping_weight_plan_with_zero_source_ratio_is_empty() -> None:
    """Zero source ratio should yield zero aggregate contribution."""
    source = MappingRange(start=1, end=3, ratio=0)
    targets = (MappingRange(start=1, end=3, ratio=None),)

    plan = mapping_weight_plan(source, targets)

    assert plan.default_weight == 0.0
    assert plan.per_index_weights is None


def test_mapping_weight_plan_with_only_zero_target_segments_is_empty() -> None:
    """All-zero target segments should produce an empty contribution plan."""
    source = MappingRange(start=1, end=3, ratio=None)
    targets = (MappingRange(start=1, end=4, ratio=0),)

    plan = mapping_weight_plan(source, targets)

    assert plan.default_weight == 0.0
    assert plan.per_index_weights is None
