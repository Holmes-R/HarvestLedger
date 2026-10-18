"""Effective-dated price resolution and frozen delivery snapshots.

M2 rule tests (marker ``m2``); they exercise the implemented service layer.

Contract exercised
------------------
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
from django.core.exceptions import ValidationError

from procurement.models import Crop, CropGrade, Farmer, PriceListEntry
from procurement.services.errors import ServiceError

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


@pytest.fixture
def paddy_grade(db):
    crop = Crop.objects.create(
        name="Paddy", moisture_threshold=Decimal("12.00"), max_moisture=Decimal("18.00")
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


# --- Price resolution (extended cases) -------------------------------------


def test_multiple_historical_entries_pick_the_latest_eligible(grade):
    first = _price(grade, "20.00", date(2025, 11, 1))
    second = _price(grade, "22.00", date(2026, 1, 1))
    third = _price(grade, "24.50", date(2026, 4, 1))
    pricing = _pricing()

    assert pricing.resolve_price(grade, date(2025, 12, 31)) == first
    assert pricing.resolve_price(grade, date(2026, 1, 1)) == second
    assert pricing.resolve_price(grade, date(2026, 2, 15)) == second
    assert pricing.resolve_price(grade, date(2026, 4, 1)) == third
    assert pricing.resolve_price(grade, date(2026, 9, 9)) == third


def test_date_before_earliest_price_is_not_eligible(grade):
    _price(grade, "24.50", date(2026, 1, 1))
    pricing = _pricing()
    with pytest.raises(pricing.PriceNotFound):
        pricing.resolve_price(grade, date(2025, 12, 31))


def test_missing_price_error_names_crop_and_grade(grade):
    pricing = _pricing()
    with pytest.raises(pricing.PriceNotFound) as excinfo:
        pricing.resolve_price(grade, date(2026, 1, 1))
    assert "Maize" in str(excinfo.value)
    assert "A" in str(excinfo.value)
    assert excinfo.value.code == "price_not_found"


# --- Append-only price creation --------------------------------------------


def test_create_price_entry_appends_history(grade):
    pricing = _pricing()
    entry = pricing.create_price_entry(grade.crop, "A", "24.50", date(2026, 1, 1))

    assert entry.pk is not None
    assert entry.crop_grade_id == grade.pk
    assert entry.price_per_kg == Decimal("24.50")
    assert entry.effective_from == date(2026, 1, 1)
    assert pricing.resolve_price(grade, date(2026, 1, 1)) == entry


def test_create_price_entry_accepts_a_grade_instance(grade):
    pricing = _pricing()
    entry = pricing.create_price_entry(grade.crop, grade, "24.50", date(2026, 1, 1))
    assert entry.crop_grade_id == grade.pk


def test_create_price_entry_rejects_invalid_rates(grade):
    pricing = _pricing()
    with pytest.raises(ValidationError):
        pricing.create_price_entry(grade.crop, "A", "0.00", date(2026, 1, 1))
    with pytest.raises(ValidationError):
        pricing.create_price_entry(grade.crop, "A", "24.555", date(2026, 1, 1))
    assert not PriceListEntry.objects.exists()


def test_create_price_entry_requires_a_crop(grade):
    pricing = _pricing()
    try:
        with pytest.raises(ValidationError) as error:
            pricing.create_price_entry(None, grade, "1.00", date(2026, 1, 1))
    finally:
        assert PriceListEntry.objects.count() == 0
    assert error.value.code == "crop_required"


def test_create_price_entry_distinguishes_missing_crop_and_grade_records(grade):
    pricing = _pricing()
    missing_crop = Crop(
        pk=99999999,
        name="Missing",
        moisture_threshold=Decimal("14.00"),
        max_moisture=Decimal("20.00"),
    )
    with pytest.raises(ServiceError) as crop_error:
        pricing.create_price_entry(missing_crop, grade, "1.00", date(2026, 1, 1))
    assert crop_error.value.code == "crop_not_found"

    missing_grade = CropGrade(pk=99999999, crop=grade.crop, code="B")
    with pytest.raises(ServiceError) as grade_error:
        pricing.create_price_entry(
            grade.crop, missing_grade, "1.00", date(2026, 1, 1)
        )
    assert grade_error.value.code == "crop_grade_not_found"
    assert PriceListEntry.objects.count() == 0


def test_create_price_entry_rejects_rate_exceeding_field_capacity(grade):
    pricing = _pricing()
    try:
        with pytest.raises(ValidationError) as error:
            pricing.create_price_entry(
                grade.crop, grade, "10000000000.00", date(2026, 1, 1)
            )
    finally:
        assert PriceListEntry.objects.count() == 0
    assert error.value.code == "max_whole_digits"


def test_create_price_entry_rejects_disallowed_grade_code(grade):
    pricing = _pricing()
    with pytest.raises(pricing.GradeNotAllowed):
        pricing.create_price_entry(grade.crop, "Z", "24.50", date(2026, 1, 1))
    assert not PriceListEntry.objects.exists()


def test_create_price_entry_rejects_invalid_crop_grade_relationship(grade, paddy_grade):
    pricing = _pricing()
    with pytest.raises(pricing.GradeNotAllowed):
        pricing.create_price_entry(grade.crop, paddy_grade, "24.50", date(2026, 1, 1))
    assert not PriceListEntry.objects.exists()


def test_duplicate_effective_date_is_rejected(grade):
    pricing = _pricing()
    pricing.create_price_entry(grade.crop, "A", "24.50", date(2026, 1, 1))

    with pytest.raises(pricing.PriceAlreadyExists):
        pricing.create_price_entry(grade.crop, "A", "99.00", date(2026, 1, 1))

    rows = PriceListEntry.objects.filter(crop_grade=grade, effective_from=date(2026, 1, 1))
    assert rows.count() == 1
    assert rows.get().price_per_kg == Decimal("24.50")  # never re-priced


def test_database_uniqueness_conflict_reports_price_already_exists(grade, monkeypatch):
    from procurement.services import pricing

    pricing.create_price_entry(grade.crop, "A", "24.50", date(2026, 1, 1))

    # Simulate a concurrent insert slipping past the up-front duplicate check.
    monkeypatch.setattr(pricing, "_already_priced", lambda *args, **kwargs: False)
    with pytest.raises(pricing.PriceAlreadyExists):
        pricing.create_price_entry(grade.crop, "A", "99.00", date(2026, 1, 1))

    assert (
        PriceListEntry.objects.filter(
            crop_grade=grade, effective_from=date(2026, 1, 1)
        ).count()
        == 1
    )


def test_backdated_price_insertion_does_not_rewrite_existing_entries(grade):
    pricing = _pricing()
    original = pricing.create_price_entry(grade.crop, "A", "22.00", date(2026, 1, 1))
    later = pricing.create_price_entry(grade.crop, "A", "30.00", date(2026, 1, 10))
    assert pricing.resolve_price(grade, date(2026, 1, 6)) == original

    backdated = pricing.create_price_entry(grade.crop, "A", "10.00", date(2026, 1, 5))
    assert pricing.resolve_price(grade, date(2026, 1, 6)) == backdated

    original.refresh_from_db()
    later.refresh_from_db()
    assert original.price_per_kg == Decimal("22.00")
    assert original.effective_from == date(2026, 1, 1)
    assert later.price_per_kg == Decimal("30.00")
    assert later.effective_from == date(2026, 1, 10)
