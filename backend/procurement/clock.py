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

Clock interface / injection
---------------------------
``Clock`` is the small interface the services depend on: ``now()`` returns the
current timezone-aware instant (UTC) and ``today()`` the IST business date.
Services take an explicit ``clock`` argument (dependency injection) and fall back
to :func:`get_clock`. :func:`use_clock` installs a *context-local* override for
tests using a :class:`contextvars.ContextVar` -- there is **no process-global
mutation** and no clock HTTP header or endpoint.

Audit timestamps (``created_at``, ``recorded_at``, ``finalised_at``, ``paid_at``)
use real aware instants from ``django.utils.timezone.now()``; the business clock
is consulted only for business *dates*.

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

``tests/integration/test_payouts.py`` (marked ``m2``) pins the implemented
behaviour of these decisions.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
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


_DEFAULT_CLOCK: Clock = SystemClock()
_clock_override: ContextVar[Clock | None] = ContextVar(
    "procurement_clock_override", default=None
)


def get_clock() -> Clock:
    """Return the clock in effect for the current context.

    Returns the stable default :class:`SystemClock` unless the current context
    has installed an override with :func:`use_clock`. The default is never
    reassigned, so there is no process-global clock mutation.
    """
    return _clock_override.get() or _DEFAULT_CLOCK


@contextmanager
def use_clock(clock: Clock) -> Iterator[None]:
    """Install ``clock`` for the current context only; always restored.

    Backed by a :class:`contextvars.ContextVar`, so the override is context-local
    (safe under threads and async tasks) rather than a process global. This is a
    scoped test aid, not an HTTP-header or endpoint-driven switch.
    """
    token = _clock_override.set(clock)
    try:
        yield
    finally:
        _clock_override.reset(token)


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


def business_week_bounds(
    instant: datetime, tz: ZoneInfo = BUSINESS_TIMEZONE
) -> tuple[date, date]:
    """Return the Monday..Sunday bounds of the business week containing ``instant``.

    Combines :func:`business_date` (UTC instant -> IST date) with
    :func:`week_bounds`, so a Sunday-evening UTC instant maps to the following
    Monday-based week.
    """
    return week_bounds(business_date(instant, tz))
