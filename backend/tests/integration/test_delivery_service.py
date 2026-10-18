"""Delivery recording orchestration (M2): price resolution + frozen snapshot."""

from datetime import date
from decimal import Decimal

import pytest

from procurement.models import Crop, CropGrade, Delivery, Farmer, PriceListEntry
from procurement.services import delivery, pricing

pytestmark = pytest.mark.m2

DELIVERED_ON = date(2026, 1, 6)


@pytest.fixture
def farmer(db):
    return Farmer.objects.create(name="Asha", phone="9000000001", village="Kolar")


@pytest.fixture
def grade(db):
    crop = Crop.objects.create(
        name="Maize", moisture_threshold=Decimal("14.00"), max_moisture=Decimal("20.00")
    )
    return CropGrade.objects.create(crop=crop, code="A")


def test_missing_price_writes_nothing(farmer, grade):
    with pytest.raises(pricing.PriceNotFound):
        delivery.record_delivery(
            farmer=farmer,
            crop_grade=grade,
            delivered_on=DELIVERED_ON,
            gross_weight_kg=Decimal("100.000"),
            moisture_percent=Decimal("14.00"),
        )
    assert Delivery.objects.count() == 0


def test_freezes_threshold_price_and_breakdown(farmer, grade):
    entry = PriceListEntry.objects.create(
        crop_grade=grade,
        price_per_kg=Decimal("24.50"),
        effective_from=date(2026, 1, 1),
    )
    snapshot = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=DELIVERED_ON,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("17.60"),
    )

    assert snapshot.threshold_used == Decimal("14.00")
    assert snapshot.applied_price == Decimal("24.50")
    assert snapshot.price_list_entry_id == entry.pk
    assert snapshot.deduction_percent == Decimal("3.00")
    assert snapshot.deduction_kg == Decimal("3.00000")
    assert snapshot.net_kg == Decimal("97.00000")
    assert snapshot.amount == Decimal("2376.50")
    assert snapshot.payout_id is None
    assert snapshot.kind == "PROCUREMENT"


def test_moisture_over_max_writes_nothing(farmer, grade):
    PriceListEntry.objects.create(
        crop_grade=grade,
        price_per_kg=Decimal("24.50"),
        effective_from=date(2026, 1, 1),
    )
    with pytest.raises(delivery.MoistureExceedsMaximum):
        delivery.record_delivery(
            farmer=farmer,
            crop_grade=grade,
            delivered_on=DELIVERED_ON,
            gross_weight_kg=Decimal("100.000"),
            moisture_percent=Decimal("20.01"),
        )
    assert Delivery.objects.count() == 0
