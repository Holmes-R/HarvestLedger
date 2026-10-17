"""Specified-but-pending tests for late-delivery and correction timing.

Payout generation is intentionally not implemented yet (M2). These tests record
the weekly-grouping behaviour the engine must provide once the timing policy is
fixed; they stay skipped until then. See the "UNRESOLVED TIMING POLICY" list in
:mod:`procurement.clock`.
"""

import pytest

PENDING = pytest.mark.skip(reason="Pending M2 payout generation engine")


@PENDING
def test_late_delivery_joins_next_open_week_when_week_already_finalised():
    """A delivery whose accounting date falls in an already FINALISED week is
    grouped into a supplementary payout for the same week (per resolved policy),
    or the next open week if policy rolls forward."""


@PENDING
def test_late_delivery_joins_current_draft_of_its_week():
    """A delivery dated within a week that still has a DRAFT payout joins that
    DRAFT rather than creating a new one."""


@PENDING
def test_sunday_ist_delivery_belongs_to_that_weeks_payout():
    """A delivery at Sunday 23:59 IST is grouped into the week ending that same
    Sunday, not the following week."""


@PENDING
def test_monday_ist_after_midnight_starts_a_new_week():
    """A delivery at Monday 00:05 IST (Sunday 18:35 UTC) belongs to the new
    Monday-starting week even though its UTC date is Sunday."""


@PENDING
def test_correction_accounting_date_is_ist_business_today():
    """A correction recorded at 18:35 UTC (Monday 00:05 IST) is stamped with the
    Monday business date via get_clock().today()."""


@PENDING
def test_correction_targets_week_of_its_accounting_date():
    """The correction's accounting_date -- not the original delivery's date --
    selects the payout week it is assigned to."""


@PENDING
def test_correction_after_paid_week_creates_supplementary_payout():
    """A correction dated into an already PAID week produces a supplementary
    payout (same week or next open week per unresolved policy item 2)."""


@PENDING
def test_future_business_date_is_rejected_using_ist_clock():
    """A delivered_on after get_clock().today() (IST) is rejected, so a Sunday
    UTC date cannot be mistaken for a future IST date."""


@PENDING
def test_intraday_cutoff_policy_is_applied():
    """Pending policy item 1: records after the agreed daily cutoff roll into the
    next business day/week."""
