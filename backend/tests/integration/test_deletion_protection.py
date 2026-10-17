"""Deletion-protection tests.

Financial history must survive: deleting a farmer, grade, crop, price entry,
payout or an original delivery that something still references must be blocked
by ``on_delete=PROTECT`` rather than silently cascaded away.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db.models import ProtectedError

from procurement.models import (
    Advance,
    Crop,
    CropGrade,
    Delivery,
    DeliveryKind,
    Farmer,
    Payout,
    PriceListEntry,
)


@pytest.fixture
def history(db):
    crop = Crop.objects.create(
        name="Maize", moisture_threshold=Decimal("14.00"), max_moisture=Decimal("20.00")
    )
    grade = CropGrade.objects.create(crop=crop, code="A")
    price = PriceListEntry.objects.create(
        crop_grade=grade,
        price_per_kg=Decimal("24.50"),
        effective_from=date(2026, 1, 1),
    )
    farmer = Farmer.objects.create(name="Asha", phone="9000000000", village="Kolar")
    advance = Advance.objects.create(
        farmer=farmer, amount=Decimal("1000.00"), given_on=date(2026, 1, 3)
    )
    payout = Payout.objects.create(
        farmer=farmer, week_start=date(2026, 1, 5), week_end=date(2026, 1, 11)
    )
    delivery = Delivery.objects.create(
        farmer=farmer,
        kind=DeliveryKind.PROCUREMENT,
        crop_grade=grade,
        delivered_on=date(2026, 1, 6),
        accounting_date=date(2026, 1, 6),
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("15.00"),
        applied_price=Decimal("24.50"),
        price_list_entry=price,
        amount=Decimal("2450.00"),
        payout=payout,
    )
    return {
        "crop": crop,
        "grade": grade,
        "price": price,
        "farmer": farmer,
        "advance": advance,
        "payout": payout,
        "delivery": delivery,
    }


def test_deleting_referenced_price_entry_is_protected(history):
    with pytest.raises(ProtectedError):
        history["price"].delete()


def test_deleting_farmer_with_history_is_protected(history):
    with pytest.raises(ProtectedError):
        history["farmer"].delete()


def test_deleting_grade_in_use_is_protected(history):
    with pytest.raises(ProtectedError):
        history["grade"].delete()


def test_deleting_crop_whose_grade_is_referenced_is_protected(history):
    with pytest.raises(ProtectedError):
        history["crop"].delete()


def test_deleting_payout_with_delivery_is_protected(history):
    with pytest.raises(ProtectedError):
        history["payout"].delete()


def test_deleting_original_delivery_with_correction_is_protected(history):
    Delivery.objects.create(
        farmer=history["farmer"],
        kind=DeliveryKind.CREDIT_NOTE,
        original_delivery=history["delivery"],
        correction_magnitude=Decimal("50.00"),
        reason="Moisture re-measured",
    )
    with pytest.raises(ProtectedError):
        history["delivery"].delete()


def test_correction_note_needs_no_measurements(history):
    note = Delivery.objects.create(
        farmer=history["farmer"],
        kind=DeliveryKind.DEBIT_NOTE,
        original_delivery=history["delivery"],
        correction_magnitude=Decimal("25.00"),
        reason="Rate correction",
    )
    assert note.gross_weight_kg is None
    assert note.moisture_percent is None
