"""Effective-dated price resolution and frozen delivery snapshots.

M2 rule tests (marker ``m2``) except where noted; they are expected to fail
until the M2 service layer exists and are intentionally not skipped.

Contract exercised (to be provided by M2)
-----------------------------------------
``procurement.services.pricing.resolve_price(crop_grade, on_date) ->
PriceListEntry`` -- the row with the greatest ``effective_from <= on_date``,
raising ``procurement.services.pricing.PriceNotFound`` for a crop/grade with no
eligible row.

``procurement.services.delivery.record_delivery(farmer=..., crop_grade=...,
delivered_on=..., gross_weight_kg=..., moisture_percent=...) -> Delivery`` --
resolves and *freezes* ``applied_price`` / ``price_list_entry`` on the delivery.
"""

from datetime import date
from decimal import Decimal

import pytest

from procurement.models import Crop, CropGrade, Farmer, PriceListEntry

pytestmark = pytest.mark.m2


def _pricing():
    from procurement.services import pricing

    return pricing


@pytest.fixture
def grade(db):
    crop = Crop.objects.create(
        name="Maize", moisture_threshold=Decimal("14.00"), max_moisture=Decimal("20.00")
    )
    return CropGrade.objects.create(crop=crop, code="A")


def _price(grade, amount, effective_from):
    return PriceListEntry.objects.create(
        crop_grade=grade, price_per_kg=Decimal(amount), effective_from=effective_from
    )


def test_exact_effective_date_wins(grade):
    entry = _price(grade, "24.50", date(2026, 1, 1))
    assert _pricing().resolve_price(grade, date(2026, 1, 1)) == entry


def test_latest_eligible_price_is_used(grade):
    _price(grade, "22.00", date(2025, 11, 1))
    newer = _price(grade, "24.50", date(2026, 1, 1))
    _price(grade, "99.00", date(2026, 4, 1))
    assert _pricing().resolve_price(grade, date(2026, 3, 15)) == newer


def test_missing_crop_grade_combination_raises(grade):
    pricing = _pricing()
    with pytest.raises(pricing.PriceNotFound):
        pricing.resolve_price(grade, date(2026, 1, 1))


def test_future_only_price_is_not_eligible(grade):
    _price(grade, "24.50", date(2026, 1, 7))
    pricing = _pricing()
    with pytest.raises(pricing.PriceNotFound):
        pricing.resolve_price(grade, date(2026, 1, 6))


def test_historical_snapshot_survives_a_later_backdated_price(grade):
    from procurement.services import delivery

    original = _price(grade, "24.50", date(2026, 1, 1))
    farmer = Farmer.objects.create(name="Asha", phone="9000000009", village="Kolar")

    snapshot = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=date(2026, 1, 6),
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
    )
    assert snapshot.applied_price == Decimal("24.50")
    assert snapshot.price_list_entry_id == original.pk

    frozen = {
        field: getattr(snapshot, field)
        for field in (
            "threshold_used",
            "deduction_percent",
            "deduction_kg",
            "net_kg",
            "amount",
            "applied_price",
            "price_list_entry_id",
            "calculation_version",
        )
    }

    # Both entries are added after the delivery. The backdated one would now
    # win a fresh lookup for January 6, but must not rewrite this delivery.
    backdated = _price(grade, "10.00", date(2026, 1, 5))
    _price(grade, "30.00", date(2026, 1, 10))
    assert _pricing().resolve_price(grade, date(2026, 1, 6)) == backdated

    snapshot.refresh_from_db()
    assert {field: getattr(snapshot, field) for field in frozen} == frozen
