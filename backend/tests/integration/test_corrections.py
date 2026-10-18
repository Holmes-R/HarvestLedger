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
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from procurement.clock import FrozenClock, use_clock
from procurement.models import (
    Crop,
    CropGrade,
    Delivery,
    DeliveryKind,
    Farmer,
    Payout,
    PayoutStatus,
)

WEEK_START = date(2026, 1, 5)  # Monday
NEXT_WEEK_START = date(2026, 1, 12)


@pytest.fixture
def farmer(db):
    return Farmer.objects.create(name="Asha", phone="9000000001", village="Kolar")


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
        threshold_used=Decimal("14.00"),
        deduction_percent=Decimal("0.00"),
        deduction_kg=Decimal("0.00000"),
        net_kg=Decimal("100.00000"),
        applied_price=Decimal("24.50"),
        amount=Decimal(amount),
    )


def _finalised_original(farmer, grade, status=PayoutStatus.FINALISED):
    original = _procurement(farmer, grade)
    payout = Payout.objects.create(
        farmer=farmer,
        week_start=WEEK_START,
        week_end=date(2026, 1, 11),
        status=status,
        gross_amount=original.amount,
        net_amount=original.amount,
        finalised_at=datetime(2026, 1, 11, 12, 0, tzinfo=UTC),
        paid_at=(
            datetime(2026, 1, 12, 12, 0, tzinfo=UTC)
            if status == PayoutStatus.PAID
            else None
        ),
    )
    original.payout = payout
    original.save(update_fields=["payout"])
    return original, payout


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
@pytest.mark.parametrize("status", [PayoutStatus.FINALISED, PayoutStatus.PAID])
def test_correction_inherits_farmer_and_stores_magnitude(farmer, grade, status):
    from procurement.services import corrections

    original, _ = _finalised_original(farmer, grade, status=status)
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
@pytest.mark.parametrize("original_status", [None, PayoutStatus.DRAFT])
def test_correction_requires_finalised_or_paid_original(farmer, grade, original_status):
    from procurement.services import corrections

    original = _procurement(farmer, grade)
    if original_status is not None:
        payout = Payout.objects.create(
            farmer=farmer,
            week_start=WEEK_START,
            week_end=date(2026, 1, 11),
            status=original_status,
        )
        original.payout = payout
        original.save(update_fields=["payout"])

    with pytest.raises(ValidationError):
        corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal("50.00"),
            reason="weight re-check",
        )
    assert not Delivery.objects.filter(original_delivery=original).exists()


@pytest.mark.m2
def test_correction_is_stamped_with_business_date(farmer, grade):
    from procurement.services import corrections

    original, _ = _finalised_original(farmer, grade)
    with use_clock(_frozen(date(2026, 2, 10))):
        note = corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.DEBIT_NOTE,
            magnitude=Decimal("30.00"),
            reason="moisture dispute",
        )

    assert note.accounting_date == date(2026, 2, 10)
    assert note.accounting_date != original.delivered_on


@pytest.mark.m2
def test_credit_note_increases_next_payout(farmer, grade):
    from procurement.services import corrections, payouts

    original, original_payout = _finalised_original(farmer, grade)
    current = _procurement(farmer, grade, on_date=date(2026, 1, 13))
    with use_clock(_frozen(date(2026, 1, 13))):
        note = corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal("50.00"),
            reason="weight under-counted",
        )
        payout = payouts.build_weekly_payout(farmer, NEXT_WEEK_START)

    assert note.accounting_date == date(2026, 1, 13)
    assert payout.gross_amount == Decimal("2500.00")
    assert set(payout.deliveries.values_list("pk", flat=True)) == {current.pk, note.pk}
    assert original.payout_id == original_payout.pk


@pytest.mark.m2
def test_debit_note_decreases_next_payout(farmer, grade):
    from procurement.services import corrections, payouts

    original, _ = _finalised_original(farmer, grade)
    current = _procurement(farmer, grade, on_date=date(2026, 1, 13))
    with use_clock(_frozen(date(2026, 1, 13))):
        note = corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.DEBIT_NOTE,
            magnitude=Decimal("50.00"),
            reason="moisture dispute",
        )
        payout = payouts.build_weekly_payout(farmer, NEXT_WEEK_START)

    assert note.accounting_date == date(2026, 1, 13)
    assert payout.gross_amount == Decimal("2400.00")
    assert set(payout.deliveries.values_list("pk", flat=True)) == {current.pk, note.pk}
    assert original.payout_id != payout.pk


@pytest.mark.m2
def test_correction_joining_a_finalised_week_needs_a_supplementary(farmer, grade):
    from procurement.services import corrections, payouts

    original, first = _finalised_original(farmer, grade)
    with use_clock(_frozen(date(2026, 1, 6))):
        note = corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal("50.00"),
            reason="late correction",
        )
        supplementary = payouts.build_weekly_payout(farmer, WEEK_START)

    assert supplementary.pk != first.pk
    assert supplementary.gross_amount == Decimal("50.00")
    assert set(supplementary.deliveries.values_list("pk", flat=True)) == {note.pk}
    assert original.payout_id == first.pk


@pytest.mark.m2
def test_correction_is_included_once_and_original_snapshot_is_unchanged(farmer, grade):
    from procurement.services import corrections, payouts

    original, original_payout = _finalised_original(farmer, grade)
    frozen = {
        field: getattr(original, field)
        for field in (
            "farmer_id",
            "payout_id",
            "gross_weight_kg",
            "moisture_percent",
            "threshold_used",
            "deduction_percent",
            "deduction_kg",
            "net_kg",
            "applied_price",
            "amount",
            "calculation_version",
        )
    }
    with use_clock(_frozen(date(2026, 1, 13))):
        note = corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal("50.00"),
            reason="weight re-check",
        )
        first = payouts.build_weekly_payout(farmer, NEXT_WEEK_START)
        second = payouts.build_weekly_payout(farmer, NEXT_WEEK_START)

    assert first.pk == second.pk
    assert first.gross_amount == Decimal("50.00")
    assert set(second.deliveries.values_list("pk", flat=True)) == {note.pk}
    original.refresh_from_db()
    assert {field: getattr(original, field) for field in frozen} == frozen
    assert original.payout_id == original_payout.pk


@pytest.mark.m2
def test_correction_accepts_an_injected_business_clock(farmer, grade):
    from procurement.services import corrections

    original, _ = _finalised_original(farmer, grade)
    note = corrections.record_correction(
        original_delivery=original,
        kind=DeliveryKind.CREDIT_NOTE,
        magnitude=Decimal("10.00"),
        reason="weight re-check",
        clock=_frozen(date(2026, 3, 4)),
    )

    assert note.accounting_date == date(2026, 3, 4)
