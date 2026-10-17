"""Credit/debit note corrections.

M1 model constraints (a note must reference an original delivery, carry a
positive magnitude and a non-blank reason) pass at M1. The M2 service layer
(marker ``m2``) is exercised for farmer inheritance, credit/debit sign,
business-date stamping and inclusion in the next eligible payout; those tests are
expected to fail until M2 exists and are not skipped.

Contract exercised (to be provided by M2)
-----------------------------------------
``procurement.services.corrections.record_correction(
    original_delivery, kind, magnitude, reason) -> Delivery`` -- creates a
CREDIT_NOTE (+) or DEBIT_NOTE (-) correction against ``original_delivery``,
inheriting its farmer and stamping ``accounting_date`` with the IST business
date (``procurement.clock.get_clock().today()``). The signed amount flows into
that date's weekly payout.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from procurement.clock import FrozenClock, use_clock
from procurement.models import Crop, CropGrade, Delivery, DeliveryKind, Farmer

WEEK_START = date(2026, 1, 5)  # Monday


@pytest.fixture
def farmer(db):
    return Farmer.objects.create(name="Asha", phone="0000000001", village="Kolar")


@pytest.fixture
def grade(db):
    crop = Crop.objects.create(
        name="Maize", moisture_threshold=Decimal("14.00"), max_moisture=Decimal("20.00")
    )
    return CropGrade.objects.create(crop=crop, code="A")


def _procurement(farmer, grade, on_date=date(2026, 1, 6), amount="2450.00"):
    return Delivery.objects.create(
        farmer=farmer,
        kind=DeliveryKind.PROCUREMENT,
        crop_grade=grade,
        delivered_on=on_date,
        accounting_date=on_date,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
        applied_price=Decimal("24.50"),
        amount=Decimal(amount),
    )


def _frozen(business_day):
    # 06:00 UTC == 11:30 IST, so the IST business date equals ``business_day``.
    instant = datetime(
        business_day.year, business_day.month, business_day.day, 6, 0, tzinfo=UTC
    )
    return FrozenClock(instant)


# --- M1 model-level rules (pass at M1) -------------------------------------


def test_note_requires_an_original_delivery(farmer):
    with pytest.raises(IntegrityError), transaction.atomic():
        Delivery.objects.create(
            farmer=farmer,
            kind=DeliveryKind.CREDIT_NOTE,
            correction_magnitude=Decimal("10.00"),
            reason="weight re-check",
        )


def test_note_requires_a_reason(farmer, grade):
    original = _procurement(farmer, grade)
    with pytest.raises(IntegrityError), transaction.atomic():
        Delivery.objects.create(
            farmer=farmer,
            kind=DeliveryKind.DEBIT_NOTE,
            original_delivery=original,
            correction_magnitude=Decimal("10.00"),
            reason="",
        )


def test_note_requires_positive_magnitude(farmer, grade):
    original = _procurement(farmer, grade)
    with pytest.raises(IntegrityError), transaction.atomic():
        Delivery.objects.create(
            farmer=farmer,
            kind=DeliveryKind.CREDIT_NOTE,
            original_delivery=original,
            correction_magnitude=Decimal("0.00"),
            reason="zero",
        )


# --- M2 service rules (expected to fail until M2) --------------------------


@pytest.mark.m2
def test_correction_inherits_farmer_and_stores_magnitude(farmer, grade):
    from procurement.services import corrections

    original = _procurement(farmer, grade)
    note = corrections.record_correction(
        original_delivery=original,
        kind=DeliveryKind.CREDIT_NOTE,
        magnitude=Decimal("50.00"),
        reason="weight re-check",
    )

    assert note.farmer_id == original.farmer_id
    assert note.original_delivery_id == original.pk
    assert note.correction_magnitude == Decimal("50.00")


@pytest.mark.m2
def test_correction_is_stamped_with_business_date(farmer, grade):
    from procurement.services import corrections

    original = _procurement(farmer, grade)
    with use_clock(_frozen(date(2026, 2, 10))):
        note = corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.DEBIT_NOTE,
            magnitude=Decimal("30.00"),
            reason="moisture dispute",
        )

    assert note.accounting_date == date(2026, 2, 10)


@pytest.mark.m2
def test_credit_note_increases_next_payout(farmer, grade):
    from procurement.services import corrections, payouts

    original = _procurement(farmer, grade)
    with use_clock(_frozen(date(2026, 1, 6))):
        corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal("50.00"),
            reason="weight under-counted",
        )
        payout = payouts.build_weekly_payout(farmer, WEEK_START)

    assert payout.gross_amount == Decimal("2500.00")


@pytest.mark.m2
def test_debit_note_decreases_next_payout(farmer, grade):
    from procurement.services import corrections, payouts

    original = _procurement(farmer, grade)
    with use_clock(_frozen(date(2026, 1, 6))):
        corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.DEBIT_NOTE,
            magnitude=Decimal("50.00"),
            reason="moisture dispute",
        )
        payout = payouts.build_weekly_payout(farmer, WEEK_START)

    assert payout.gross_amount == Decimal("2400.00")


@pytest.mark.m2
def test_correction_joining_a_finalised_week_needs_a_supplementary(farmer, grade):
    from procurement.services import corrections, payouts

    original = _procurement(farmer, grade)
    with use_clock(_frozen(date(2026, 1, 6))):
        first = payouts.build_weekly_payout(farmer, WEEK_START)
        payouts.finalise_payout(first)

        corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal("50.00"),
            reason="late correction",
        )
        supplementary = payouts.build_weekly_payout(farmer, WEEK_START)

    assert supplementary.pk != first.pk
    assert supplementary.gross_amount == Decimal("50.00")
