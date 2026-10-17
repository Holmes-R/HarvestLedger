"""M1 business-clock tests: IST business dates and Monday-based weeks."""

from datetime import UTC, date, datetime

import pytest

from procurement import clock
from procurement.clock import (
    BUSINESS_TIMEZONE,
    FrozenClock,
    SystemClock,
    business_date,
    get_clock,
    use_clock,
    week_bounds,
    week_end,
    week_start,
)


def _utc(*args):
    return datetime(*args, tzinfo=UTC)


def test_business_timezone_is_ist():
    assert BUSINESS_TIMEZONE.key == "Asia/Kolkata"
    offset = datetime(2026, 1, 5, tzinfo=BUSINESS_TIMEZONE).utcoffset()
    assert offset is not None and offset.total_seconds() == 5.5 * 3600


def test_system_clock_now_is_aware_utc():
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 0


def test_get_clock_returns_system_clock_by_default():
    assert isinstance(get_clock(), SystemClock)


def test_business_date_converts_instant_to_ist_date():
    # 18:30 UTC == 00:00 next day in IST.
    assert business_date(_utc(2026, 1, 5, 18, 30)) == date(2026, 1, 6)
    # 18:29 UTC is still 23:59 the same IST day.
    assert business_date(_utc(2026, 1, 5, 18, 29)) == date(2026, 1, 5)


def test_business_date_rejects_naive_instants():
    with pytest.raises(ValueError):
        business_date(datetime(2026, 1, 5, 12, 0))


def test_frozen_clock_reports_ist_date():
    inst = _utc(2026, 1, 4, 18, 45)  # Sun 18:45 UTC
    assert FrozenClock(inst).today() == date(2026, 1, 5)  # Mon 00:15 IST


def test_use_clock_swaps_and_restores():
    frozen = FrozenClock(_utc(2026, 1, 6, 6, 0))
    with use_clock(frozen):
        assert clock.get_clock() is frozen
        assert get_clock().today() == date(2026, 1, 6)
    assert isinstance(get_clock(), SystemClock)


@pytest.mark.parametrize(
    ("day", "expected_start", "expected_end"),
    [
        (date(2026, 1, 5), date(2026, 1, 5), date(2026, 1, 11)),  # Monday
        (date(2026, 1, 11), date(2026, 1, 5), date(2026, 1, 11)),  # Sunday
        (date(2026, 1, 8), date(2026, 1, 5), date(2026, 1, 11)),  # Thursday
        (date(2026, 1, 12), date(2026, 1, 12), date(2026, 1, 18)),  # next Monday
    ],
)
def test_week_is_monday_to_sunday_inclusive(day, expected_start, expected_end):
    assert week_start(day) == expected_start
    assert week_end(day) == expected_end
    assert week_bounds(day) == (expected_start, expected_end)


def test_week_bounds_must_use_ist_not_utc():
    # Sunday 18:45 UTC is already Monday 00:15 IST, so it belongs to the Mon-Sun
    # week beginning 2026-01-05 -- NOT the UTC week ending 2026-01-04.
    instant = _utc(2026, 1, 4, 18, 45)
    ist_day = business_date(instant)
    assert ist_day == date(2026, 1, 5)
    assert week_bounds(ist_day) == (date(2026, 1, 5), date(2026, 1, 11))
    assert week_bounds(instant.date()) == (date(2025, 12, 29), date(2026, 1, 4))
