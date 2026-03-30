"""Tests for cron utility helpers."""

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from anibridge.app.utils import cron as cron_module


def test_get_next_run_datetime_supports_integer_intervals() -> None:
    """Integer intervals should add seconds to the provided base time."""
    now = datetime(2026, 1, 1, tzinfo=UTC)

    assert cron_module.get_next_run_datetime(30, now) == datetime(
        2026, 1, 1, 0, 0, 30, tzinfo=UTC
    )


@pytest.mark.parametrize("interval", [0, -1])
def test_get_next_run_datetime_rejects_non_positive_integers(interval: int) -> None:
    """Integer intervals must be strictly positive."""
    with pytest.raises(ValueError, match="greater than 0"):
        cron_module.get_next_run_datetime(interval, datetime(2026, 1, 1, tzinfo=UTC))


def test_get_next_run_datetime_supports_cron_expressions() -> None:
    """Cron expressions should be resolved from the provided base datetime."""
    now = datetime(2026, 1, 1, 12, 15, tzinfo=UTC)

    assert cron_module.get_next_run_datetime("0 * * * *", now) == datetime(
        2026, 1, 1, 13, 0, tzinfo=UTC
    )


def test_get_next_run_datetime_rejects_invalid_inputs() -> None:
    """Invalid cron strings and unsupported types should raise ValueError."""
    now = datetime(2026, 1, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="Invalid cron expression"):
        cron_module.get_next_run_datetime("not-cron", now)

    with pytest.raises(ValueError, match="Invalid interval type"):
        cron_module.get_next_run_datetime(cast(Any, 3.14), now)


def test_get_next_interval_seconds_uses_next_run() -> None:
    """Interval seconds should be derived from the computed next run time."""
    now = datetime(2026, 1, 1, 12, 15, tzinfo=UTC)

    assert cron_module.get_next_interval_seconds(45, now) == 45
    assert cron_module.get_next_interval_seconds("0 * * * *", now) == 45 * 60


def test_format_interval_and_enablement_helpers() -> None:
    """Formatting and enabled checks should distinguish valid interval values."""
    assert cron_module.format_interval(15) == "15s"
    assert cron_module.format_interval("0 * * * *") == "cron(0 * * * *)"
    assert cron_module.format_interval(cast(Any, object())).startswith("<object object")

    assert cron_module.is_enabled_interval(1) is True
    assert cron_module.is_enabled_interval(0) is False
    assert cron_module.is_enabled_interval("0 * * * *") is True
    assert cron_module.is_enabled_interval("not-cron") is False
    assert cron_module.is_enabled_interval(cast(Any, None)) is False
