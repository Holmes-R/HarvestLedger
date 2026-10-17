"""Weekly grouping and business-date rules available in M1."""

from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from procurement.models import (
    Crop,
    CropGrade,
    Delivery,
    DeliveryKind,
    Farmer,
    Payout,
    PayoutStatus,
    PriceListEntry,
)


@pytest.fixture
def farmer(db):
    return Farmer.objects.create(name="Asha", phone="9000000000", village="Kolar")


@pytest.fixture
def priced(db):
    crop = Crop.objects.create(
        name="Maize", moisture_threshold=Decimal("14.00"), max_moisture=Decimal("20.00")
    )
    grade = CropGrade.objects.create(crop=crop, code="A")
    price = PriceListEntry.objects.create(
        crop_grade=grade, price_per_kg=Decimal("24.50"), effective_from=date(2026, 1, 1)
    )
    return grade, price


def _create_payout(farmer, week_start=date(2026, 1, 5)):
    return Payout.objects.create(
        farmer=farmer, week_start=week_start, week_end=date(2026, 1, 11)
    )


def test_only_one_draft_payout_per_farmer_week(farmer):
    _create_payout(farmer)
    with pytest.raises(IntegrityError), transaction.atomic():
        _create_payout(farmer)


def test_supplementary_draft_allowed_after_earlier_payout_finalised(farmer):
    first = _create_payout(farmer)
    first.status = PayoutStatus.FINALISED
    first.save(update_fields=["status"])

    supplementary = _create_payout(farmer)  # same week, late/unassigned records
    assert supplementary.status == PayoutStatus.DRAFT

    with pytest.raises(IntegrityError), transaction.atomic():
        _create_payout(farmer)  # still only one DRAFT at a time


def test_week_start_and_end_are_not_unconditionally_unique(farmer):
    finalised = _create_payout(farmer)
    finalised.status = PayoutStatus.PAID
    finalised.save(update_fields=["status"])
    draft = _create_payout(farmer)

    pks = set(Payout.objects.filter(farmer=farmer).values_list("pk", flat=True))
    assert pks == {finalised.pk, draft.pk}


def test_different_weeks_are_independent(farmer):
    _create_payout(farmer, week_start=date(2026, 1, 5))
    Payout.objects.create(
        farmer=farmer, week_start=date(2026, 1, 12), week_end=date(2026, 1, 18)
    )
    assert Payout.objects.filter(farmer=farmer).count() == 2


def _create_procurement(farmer, grade, price, delivered_on, accounting_date):
    return Delivery.objects.create(
        farmer=farmer,
        kind=DeliveryKind.PROCUREMENT,
        crop_grade=grade,
        delivered_on=delivered_on,
        accounting_date=accounting_date,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
        applied_price=Decimal("24.50"),
        price_list_entry=price,
        amount=Decimal("2450.00"),
    )


def test_procurement_accounting_date_must_equal_delivered_on(farmer, priced):
    grade, price = priced
    with pytest.raises(IntegrityError), transaction.atomic():
        _create_procurement(farmer, grade, price, date(2026, 1, 6), date(2026, 1, 7))


def test_procurement_requires_delivered_on(farmer, priced):
    grade, price = priced
    with pytest.raises(IntegrityError), transaction.atomic():
        _create_procurement(farmer, grade, price, None, None)


def test_procurement_with_matching_dates_is_accepted(farmer, priced):
    grade, price = priced
    delivery = _create_procurement(
        farmer, grade, price, date(2026, 1, 6), date(2026, 1, 6)
    )
    assert delivery.accounting_date == delivery.delivered_on


def test_correction_note_needs_no_business_dates(farmer, priced):
    grade, price = priced
    original = _create_procurement(
        farmer, grade, price, date(2026, 1, 6), date(2026, 1, 6)
    )
    note = Delivery.objects.create(
        farmer=farmer,
        kind=DeliveryKind.CREDIT_NOTE,
        original_delivery=original,
        correction_magnitude=Decimal("50.00"),
        reason="Moisture re-measured",
    )
    assert note.delivered_on is None
    assert note.accounting_date is None
