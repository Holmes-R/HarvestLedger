"""Pure advance-recovery calculation (M2). No database."""

from decimal import Decimal

import pytest

from procurement.services import money

pytestmark = pytest.mark.m2


def test_recovers_thirty_percent_when_outstanding_is_larger():
    assert money.advance_recovery(
        Decimal("2450.00"), Decimal("1000.00")
    ) == Decimal("735.00")


def test_recovers_only_the_remaining_outstanding_balance():
    assert money.advance_recovery(
        Decimal("2450.00"), Decimal("265.00")
    ) == Decimal("265.00")


def test_cap_rounds_an_exact_half_cent_up():
    # 0.05 * 0.30 = 0.015 -> HALF_UP -> 0.02.
    assert money.advance_recovery(Decimal("0.05"), Decimal("1.00")) == Decimal(
        "0.02"
    )


def test_no_recovery_without_outstanding():
    assert money.advance_recovery(Decimal("2450.00"), Decimal("0.00")) == Decimal(
        "0.00"
    )


@pytest.mark.parametrize("gross", ["0.00", "-10.00"])
def test_no_recovery_on_zero_or_negative_gross(gross):
    assert money.advance_recovery(Decimal(gross), Decimal("100.00")) == Decimal(
        "0.00"
    )
