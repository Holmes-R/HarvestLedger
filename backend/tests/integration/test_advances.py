"""Advance posting rules (M2)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from procurement.models import Advance, Farmer
from procurement.services import advances

pytestmark = pytest.mark.m2

WEEK_START = date(2026, 1, 5)


@pytest.fixture
def farmer(db):
    return Farmer.objects.create(name="Asha", phone="9000000001", village="Kolar")


def test_posting_accumulates_outstanding_balance(farmer):
    advances.post_advance(farmer, Decimal("300.00"), WEEK_START)
    advances.post_advance(farmer, Decimal("200.50"), WEEK_START + timedelta(days=1))
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("500.50")


def test_same_day_advances_are_separate_records(farmer):
    first = advances.post_advance(farmer, Decimal("100.00"), WEEK_START)
    second = advances.post_advance(farmer, Decimal("250.00"), WEEK_START)

    assert first.pk != second.pk
    assert Advance.objects.filter(farmer=farmer, given_on=WEEK_START).count() == 2
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("350.00")


@pytest.mark.parametrize("amount", ["0.00", "-10.00"])
def test_nonpositive_amount_is_rejected(farmer, amount):
    with pytest.raises(ValidationError):
        advances.post_advance(farmer, Decimal(amount), WEEK_START)

    assert Advance.objects.count() == 0
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("0.00")


def test_overprecise_amount_is_rejected(farmer):
    with pytest.raises(ValidationError):
        advances.post_advance(farmer, Decimal("10.001"), WEEK_START)

    assert Advance.objects.count() == 0
