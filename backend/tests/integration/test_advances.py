"""Advance posting and reconciliation rules (M2)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from procurement.models import (
    Advance,
    Crop,
    CropGrade,
    Delivery,
    DeliveryKind,
    Farmer,
    Payout,
    PayoutStatus,
)
from procurement.services import advances, payouts

pytestmark = pytest.mark.m2

WEEK_START = date(2026, 1, 5)


@pytest.fixture
def farmer(db):
    return Farmer.objects.create(name="Asha", phone="9000000001", village="Kolar")


def _procurement(farmer, on_date, amount):
    crop = Crop.objects.create(
        name="Maize", moisture_threshold=Decimal("14.00"), max_moisture=Decimal("20.00")
    )
    grade = CropGrade.objects.create(crop=crop, code="A")
    return Delivery.objects.create(
        farmer=farmer,
        kind=DeliveryKind.PROCUREMENT,
        crop_grade=grade,
        delivered_on=on_date,
        accounting_date=on_date,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
        threshold_used=Decimal("14.00"),
        deduction_percent=Decimal("0.00"),
        deduction_kg=Decimal("0.00000"),
        net_kg=Decimal("100.00000"),
        applied_price=Decimal("10.00"),
        amount=Decimal(amount),
    )


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


def test_advance_that_would_overflow_outstanding_balance_is_atomic(farmer):
    maximum = Decimal("999999999999.99")
    first = advances.post_advance(farmer, maximum, WEEK_START)
    with pytest.raises(ValidationError) as error:
        advances.post_advance(farmer, Decimal("0.01"), WEEK_START)
    assert error.value.code == "max_whole_digits"
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == maximum
    assert list(Advance.objects.values_list("pk", "amount")) == [
        (first.pk, maximum)
    ]


def test_posting_requires_a_saved_farmer():
    with pytest.raises(ValidationError):
        advances.post_advance(None, Decimal("10.00"), WEEK_START)


def test_failure_rolls_back_the_advance_and_the_balance(farmer, monkeypatch):
    def boom(self, *args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(Farmer, "save", boom)
    with pytest.raises(RuntimeError):
        advances.post_advance(farmer, Decimal("100.00"), WEEK_START)

    assert Advance.objects.count() == 0
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("0.00")


def test_reconciliation_holds_before_and_after_payout_recovery(farmer):
    advances.post_advance(farmer, Decimal("1000.00"), WEEK_START)

    before = advances.assert_outstanding_reconciles(farmer)
    assert before.total_advances == Decimal("1000.00")
    assert before.total_recovered == Decimal("0.00")
    assert before.expected_outstanding == Decimal("1000.00")
    assert before.stored_outstanding == Decimal("1000.00")

    _procurement(farmer, WEEK_START, "1000.00")
    draft = payouts.build_weekly_payout(farmer, WEEK_START)
    payout = payouts.finalise_payout(draft)
    assert payout.advance_deduction == Decimal("300.00")  # 30% of gross

    after = advances.assert_outstanding_reconciles(farmer)
    assert after.total_advances == Decimal("1000.00")
    assert after.total_recovered == Decimal("300.00")
    assert after.expected_outstanding == Decimal("700.00")
    assert after.stored_outstanding == Decimal("700.00")


def test_paid_is_not_counted_as_a_second_recovery(farmer):
    advances.post_advance(farmer, Decimal("1000.00"), WEEK_START)
    _procurement(farmer, WEEK_START, "1000.00")
    payout = payouts.finalise_payout(payouts.build_weekly_payout(farmer, WEEK_START))

    Payout.objects.filter(pk=payout.pk).update(status=PayoutStatus.PAID)

    reconciliation = advances.assert_outstanding_reconciles(farmer)
    assert reconciliation.total_recovered == Decimal("300.00")
    assert reconciliation.stored_outstanding == Decimal("700.00")


def test_reconciliation_reports_drift_without_repairing_it(farmer):
    advances.post_advance(farmer, Decimal("100.00"), WEEK_START)
    Farmer.objects.filter(pk=farmer.pk).update(outstanding_advance=Decimal("999.00"))

    reconciliation = advances.reconcile_outstanding(farmer)
    assert reconciliation.total_advances == Decimal("100.00")
    assert reconciliation.expected_outstanding == Decimal("100.00")
    assert reconciliation.stored_outstanding == Decimal("999.00")
    assert reconciliation.difference == Decimal("899.00")
    assert not reconciliation.is_reconciled

    with pytest.raises(advances.AdvanceReconciliationError):
        advances.assert_outstanding_reconciles(farmer)

    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("999.00")  # not silently repaired


@pytest.mark.django_db(transaction=True)
def test_concurrent_advances_do_not_lose_balance_updates():
    from concurrent.futures import ThreadPoolExecutor

    from django.db import connections

    farmer = Farmer.objects.create(name="Asha", phone="9000000001", village="Kolar")
    workers = 12
    amount = Decimal("10.00")

    def post(_index):
        try:
            advances.post_advance(
                Farmer.objects.get(pk=farmer.pk), amount, WEEK_START
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(post, range(workers)))

    farmer.refresh_from_db()
    assert Advance.objects.filter(farmer=farmer).count() == workers
    assert farmer.outstanding_advance == amount * workers
