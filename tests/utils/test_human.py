"""Tests for human-readable duration formatting."""

import pytest

from anibridge.app.utils.human import human_duration


def test_human_duration_formats_compound_values() -> None:
    assert human_duration(90061) == "1d 1h 1m 1s"


def test_human_duration_rejects_negative_values() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        human_duration(-1)
