"""Pure advance-recovery calculation (M2). No database."""

from decimal import Decimal

import pytest

from procurement.services import money

pytestmark = pytest.mark.m2


def test_recovers_thirty_percent_when_outstanding_is_larger():
    assert money.advance_recovery(Decimal("2450.00"), Decimal("1000.00")) == Decimal(
        "735.00"
    )


def test_recovers_only_the_remaining_outstanding_balance():
    assert money.advance_recovery(Decimal("2450.00"), Decimal("265.00")) == Decimal(
        "265.00"
    )


def test_cap_rounds_an_exact_half_cent_down():
    # 0.05 * 0.30 = 0.015; 0.02 would exceed the exact 30% cap.
    assert money.advance_recovery(Decimal("0.05"), Decimal("1.00")) == Decimal("0.01")


@pytest.mark.parametrize(
    ("gross", "expected_cap"),
    [
        ("0.04", "0.01"),
        ("0.05", "0.01"),  # exact cap 0.015; 0.02 would exceed 30%
        ("0.15", "0.04"),
        ("0.35", "0.10"),
        ("100.05", "30.01"),
        ("100.10", "30.03"),
    ],
)
def test_positive_cap_never_exceeds_exact_thirty_percent(gross, expected_cap):
    gross = Decimal(gross)
    cap = money.advance_recovery_cap(gross)
    assert cap == Decimal(expected_cap)
    assert cap <= gross * Decimal("0.30")


def test_no_recovery_without_outstanding():
    assert money.advance_recovery(Decimal("2450.00"), Decimal("0.00")) == Decimal(
        "0.00"
    )


@pytest.mark.parametrize("gross", ["0.00", "-10.00"])
def test_no_recovery_on_zero_or_negative_gross(gross):
    assert money.advance_recovery(Decimal(gross), Decimal("100.00")) == Decimal("0.00")
