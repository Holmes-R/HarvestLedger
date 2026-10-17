"""Business clock and weekly-grouping design (M1).

Time representation
-------------------
* ``USE_TZ = True``. Audit timestamps (``created_at``, ``recorded_at``,
  ``finalised_at``, ``paid_at``) are stored as timezone-aware instants in UTC.
* Business dates (``Delivery.delivered_on``, ``Delivery.accounting_date``,
  ``Payout.week_start``, ``Payout.week_end``) are plain ``DateField``\\s and are
  interpreted in the business timezone ``Asia/Kolkata`` (IST, UTC+05:30, no DST).
* For an ordinary ``PROCUREMENT`` delivery ``accounting_date == delivered_on``,
  enforced by the ``delivery_accounting_matches_delivered`` check constraint.

Business-date decisions (which week a record belongs to, whether a business
date is in the future) MUST use the IST-aware clock below -- never the raw UTC
date. 18:30 UTC is already the next day in IST, so a Sunday-evening UTC instant
can be a Monday business date.

Clock interface / injection point
---------------------------------
``Clock`` is the small interface the M2 payout engine depends on. The active
clock is read through :func:`get_clock`; tests replace it with
:func:`use_clock` (see :class:`FrozenClock`). There is deliberately **no public
clock-override endpoint**: any review/development clock switching stays
server-side, non-API and non-user-controlled.

Weekly policy
-------------
* A week is Monday..Sunday inclusive. ``Payout.week_start`` is that Monday and
  ``Payout.week_end`` the following Sunday (see :func:`week_bounds`).
* At most one DRAFT payout per ``(farmer, week_start)`` -- DB partial unique
  ``payout_one_draft_farmer_week``.
* There is intentionally **no** unconditional unique ``(farmer, week)``: once an
  earlier payout for a week is FINALISED/PAID, supplementary payouts covering
  late or previously unassigned records are allowed for the same week.

Correction accounting dates -> next eligible payout
---------------------------------------------------
A credit/debit note is stamped with ``accounting_date`` = the IST business date
on which it is recorded (``get_clock().today()``). That date -- not the original
delivery's date -- selects the payout:

* the week containing ``accounting_date`` determines the target payout;
* if that week's payout is still DRAFT, the note joins it;
* if that week's payout is already FINALISED/PAID, the note needs a
  supplementary payout (same week or the next open week, per the unresolved
  policy below).

UNRESOLVED TIMING POLICY (product decision; intentionally not fixed in M1)
--------------------------------------------------------------------------
1. Intra-day cutoff: is there a time-of-day after which a record counts towards
   the next business day/week?
2. Corrections against an already PAID week: same-week supplementary payout, or
   roll forward into the next open week?
3. May more than one supplementary payout per farmer/week coexist after the
   first is finalised?
4. Are all externally supplied dates guaranteed to be IST business dates?
5. How far in the past/future may a back-dated delivery or correction be?

``tests/unit/test_payout_grouping_pending.py`` pins the behaviour once these are
decided; it is skipped until then.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

BUSINESS_TIMEZONE = ZoneInfo(settings.TIME_ZONE)
WEEK_STARTS_ON = 0  # Monday


class Clock(Protocol):
    """Time source for business-date decisions."""

    def now(self) -> datetime:
        """Return the current timezone-aware instant (UTC)."""
        ...

    def today(self) -> date:
        """Return the current business date in ``Asia/Kolkata``."""
        ...


def business_date(instant: datetime, tz: ZoneInfo = BUSINESS_TIMEZONE) -> date:
    """Map a timezone-aware instant to a business (IST) calendar date."""
    if timezone.is_naive(instant):
        raise ValueError("business_date() requires a timezone-aware instant")
    return instant.astimezone(tz).date()


class SystemClock:
    """Production clock backed by Django's UTC-aware ``timezone.now()``."""

    def now(self) -> datetime:
        return timezone.now()

    def today(self) -> date:
        return business_date(self.now())


class FrozenClock:
    """Test clock pinned to a single aware instant."""

    def __init__(self, instant: datetime):
        if timezone.is_naive(instant):
            raise ValueError("FrozenClock requires a timezone-aware instant")
        self._instant = instant

    def now(self) -> datetime:
        return self._instant

    def today(self) -> date:
        return business_date(self._instant)


_active_clock: Clock = SystemClock()


def get_clock() -> Clock:
    """Return the active business clock (M2 reads time through this)."""
    return _active_clock


@contextmanager
def use_clock(clock: Clock) -> Iterator[None]:
    """Temporarily swap the active clock. For tests only; not exposed via any API."""
    global _active_clock
    previous = _active_clock
    _active_clock = clock
    try:
        yield
    finally:
        _active_clock = previous


def week_start(value: date) -> date:
    """Return the Monday of the week containing ``value``."""
    return value - timedelta(days=value.weekday() - WEEK_STARTS_ON)


def week_end(value: date) -> date:
    """Return the Sunday of the week containing ``value``."""
    return week_start(value) + timedelta(days=6)


def week_bounds(value: date) -> tuple[date, date]:
    """Return the inclusive ``(Monday, Sunday)`` bounds of ``value``'s week."""
    start = week_start(value)
    return start, start + timedelta(days=6)
