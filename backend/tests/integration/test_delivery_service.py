"""Delivery preview / recording / editing orchestration (M2).

Covers non-persisting preview, authoritative recalculation on save, future-date
rejection against the injected IST business clock, frozen snapshots, DRAFT
consistency after edits, and rejection of edits to settled payouts.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from procurement.clock import FrozenClock
from procurement.models import (
    Crop,
    CropGrade,
    Delivery,
    Farmer,
    Payout,
    PriceListEntry,
)
from procurement.services import delivery, payouts, pricing
from procurement.services.errors import ServiceError

pytestmark = pytest.mark.m2

DELIVERED_ON = date(2026, 1, 6)  # Tuesday, in the Mon 2026-01-05 week
WEEK_START = date(2026, 1, 5)
NEXT_WEEK_START = date(2026, 1, 12)


def _frozen(business_day):
    """A clock whose IST business date is ``business_day`` (06:00 UTC == 11:30 IST)."""
    instant = datetime(
        business_day.year, business_day.month, business_day.day, 6, 0, tzinfo=UTC
    )
    return FrozenClock(instant)


def _price(grade, amount, effective_from):
    return PriceListEntry.objects.create(
        crop_grade=grade,
        price_per_kg=Decimal(amount),
        effective_from=effective_from,
    )


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


# --- Preview (non-persisting) ----------------------------------------------


def test_preview_returns_full_breakdown_and_persists_nothing(farmer, grade):
    entry = _price(grade, "24.50", date(2026, 1, 1))
    preview = delivery.preview_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=DELIVERED_ON,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("17.60"),
    )

    assert preview.farmer_id == farmer.pk
    assert preview.crop_grade == grade
    assert preview.delivered_on == DELIVERED_ON
    assert preview.accounting_date == DELIVERED_ON
    assert preview.threshold_used == Decimal("14.00")
    assert preview.price_list_entry == entry
    assert preview.applied_price == Decimal("24.50")
    assert preview.deduction_percent == Decimal("3.00")
    assert preview.deduction_kg == Decimal("3.00000")
    assert preview.net_kg == Decimal("97.00000")
    assert preview.amount == Decimal("2376.50")
    assert Delivery.objects.count() == 0


def test_preview_matches_the_saved_snapshot(farmer, grade):
    _price(grade, "24.50", date(2026, 1, 1))
    kwargs = {
        "farmer": farmer,
        "crop_grade": grade,
        "delivered_on": DELIVERED_ON,
        "gross_weight_kg": Decimal("100.000"),
        "moisture_percent": Decimal("17.60"),
    }
    preview = delivery.preview_delivery(**kwargs)
    snapshot = delivery.record_delivery(**kwargs)

    assert snapshot.threshold_used == preview.threshold_used
    assert snapshot.applied_price == preview.applied_price
    assert snapshot.price_list_entry_id == preview.price_list_entry.pk
    assert snapshot.deduction_percent == preview.deduction_percent
    assert snapshot.deduction_kg == preview.deduction_kg
    assert snapshot.net_kg == preview.net_kg
    assert snapshot.amount == preview.amount


def test_record_re_resolves_price_and_ignores_the_earlier_preview(farmer, grade):
    _price(grade, "24.50", date(2026, 1, 1))
    kwargs = {
        "farmer": farmer,
        "crop_grade": grade,
        "delivered_on": DELIVERED_ON,
        "gross_weight_kg": Decimal("100.000"),
        "moisture_percent": Decimal("14.00"),
    }
    preview = delivery.preview_delivery(**kwargs)
    assert preview.applied_price == Decimal("24.50")

    # A back-dated price added after the preview is now the effective one.
    backdated = _price(grade, "20.00", date(2026, 1, 5))
    snapshot = delivery.record_delivery(**kwargs)

    assert snapshot.applied_price == Decimal("20.00")
    assert snapshot.price_list_entry_id == backdated.pk
    assert snapshot.amount == Decimal("2000.00")


# --- Future-date validation (injected IST clock) ---------------------------


def test_future_delivery_date_is_rejected(farmer, grade):
    _price(grade, "24.50", date(2026, 1, 1))
    clock = _frozen(date(2026, 1, 6))
    kwargs = {
        "farmer": farmer,
        "crop_grade": grade,
        "delivered_on": date(2026, 1, 7),
        "gross_weight_kg": Decimal("100.000"),
        "moisture_percent": Decimal("14.00"),
        "clock": clock,
    }
    with pytest.raises(ValidationError) as preview_error:
        delivery.preview_delivery(**kwargs)
    assert preview_error.value.code == "future_delivery_date"

    with pytest.raises(ValidationError):
        delivery.record_delivery(**kwargs)
    assert Delivery.objects.count() == 0


def test_delivery_on_the_business_date_is_allowed(farmer, grade):
    _price(grade, "24.50", date(2026, 1, 1))
    snapshot = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=date(2026, 1, 6),
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
        clock=_frozen(date(2026, 1, 6)),
    )
    assert snapshot.delivered_on == date(2026, 1, 6)


def test_preview_requires_a_saved_farmer_and_grade(grade):
    with pytest.raises(ValidationError):
        delivery.preview_delivery(
            farmer=None,
            crop_grade=grade,
            delivered_on=DELIVERED_ON,
            gross_weight_kg=Decimal("100.000"),
            moisture_percent=Decimal("14.00"),
        )
    with pytest.raises(ValidationError):
        delivery.preview_delivery(
            farmer=None,
            crop_grade=None,
            delivered_on=DELIVERED_ON,
            gross_weight_kg=Decimal("100.000"),
            moisture_percent=Decimal("14.00"),
        )


def test_record_requires_a_farmer_before_locking(grade):
    _price(grade, "24.50", date(2026, 1, 1))
    try:
        with pytest.raises(ValidationError) as error:
            delivery.record_delivery(
                farmer=None,
                crop_grade=grade,
                delivered_on=DELIVERED_ON,
                gross_weight_kg=Decimal("100.000"),
                moisture_percent=Decimal("14.00"),
                clock=_frozen(date(2026, 1, 20)),
            )
    finally:
        assert Delivery.objects.count() == 0
    assert error.value.code == "farmer_required"


def test_record_rejects_a_nonexistent_farmer_with_domain_error(grade):
    _price(grade, "24.50", date(2026, 1, 1))
    missing = Farmer(pk=99999999, name="Missing", phone="9000000099", village="Kolar")
    try:
        with pytest.raises(ServiceError) as error:
            delivery.record_delivery(
                farmer=missing,
                crop_grade=grade,
                delivered_on=DELIVERED_ON,
                gross_weight_kg=Decimal("100.000"),
                moisture_percent=Decimal("14.00"),
                clock=_frozen(date(2026, 1, 20)),
            )
    finally:
        assert Delivery.objects.count() == 0
    assert error.value.code == "farmer_not_found"


def test_record_rejects_weight_exceeding_field_capacity(farmer, grade):
    _price(grade, "1.00", date(2026, 1, 1))
    try:
        with pytest.raises(ValidationError) as error:
            delivery.record_delivery(
                farmer=farmer,
                crop_grade=grade,
                delivered_on=DELIVERED_ON,
                gross_weight_kg=Decimal("1000000000.000"),
                moisture_percent=Decimal("14.00"),
                clock=_frozen(date(2026, 1, 20)),
            )
    finally:
        assert Delivery.objects.count() == 0
    assert error.value.code == "max_whole_digits"


def test_record_rejects_calculated_amount_exceeding_field_capacity(farmer, grade):
    _price(grade, "9999999999.99", date(2026, 1, 1))
    try:
        with pytest.raises(ValidationError) as error:
            delivery.record_delivery(
                farmer=farmer,
                crop_grade=grade,
                delivered_on=DELIVERED_ON,
                gross_weight_kg=Decimal("999999999.999"),
                moisture_percent=Decimal("14.00"),
                clock=_frozen(date(2026, 1, 20)),
            )
    finally:
        assert Delivery.objects.count() == 0
    assert error.value.code == "max_whole_digits"


def test_preview_rejects_an_unpersistable_calculated_amount(farmer, grade):
    _price(grade, "9999999999.99", date(2026, 1, 1))
    with pytest.raises(ValidationError) as error:
        delivery.preview_delivery(
            farmer=farmer,
            crop_grade=grade,
            delivered_on=DELIVERED_ON,
            gross_weight_kg=Decimal("999999999.999"),
            moisture_percent=Decimal("14.00"),
            clock=_frozen(date(2026, 1, 20)),
        )
    assert error.value.code == "max_whole_digits"
    assert Delivery.objects.count() == 0


def test_rounding_across_amount_capacity_is_rejected_before_save(farmer, grade):
    _price(grade, "9999000099.99", date(2026, 1, 1))
    # Both inputs fit their fields. The product is just below 10^12 but
    # ROUND_HALF_UP at 2 dp produces 1,000,000,000,000.00, which does not fit.
    assert Decimal("100.010") * Decimal("9999000099.99") == Decimal(
        "999999999999.99990"
    )
    kwargs = {
        "farmer": farmer,
        "crop_grade": grade,
        "delivered_on": DELIVERED_ON,
        "gross_weight_kg": Decimal("100.010"),
        "moisture_percent": Decimal("14.00"),
        "clock": _frozen(date(2026, 1, 20)),
    }
    with pytest.raises(ValidationError) as preview_error:
        delivery.preview_delivery(**kwargs)
    assert preview_error.value.code == "max_whole_digits"
    with pytest.raises(ValidationError) as save_error:
        delivery.record_delivery(**kwargs)
    assert save_error.value.code == "max_whole_digits"
    assert Delivery.objects.count() == 0


def test_largest_representable_weight_and_rate_can_be_saved(farmer, grade):
    _price(grade, "1.00", date(2026, 1, 1))
    weight_edge = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=DELIVERED_ON,
        gross_weight_kg=Decimal("999999999.999"),
        moisture_percent=Decimal("14.00"),
        clock=_frozen(date(2026, 1, 20)),
    )
    _price(grade, "9999999999.99", date(2026, 1, 5))
    rate_edge = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=DELIVERED_ON,
        gross_weight_kg=Decimal("1.000"),
        moisture_percent=Decimal("14.00"),
        clock=_frozen(date(2026, 1, 20)),
    )
    weight_edge.refresh_from_db()
    rate_edge.refresh_from_db()
    assert weight_edge.gross_weight_kg == Decimal("999999999.999")
    assert weight_edge.amount == Decimal("1000000000.00")
    assert rate_edge.applied_price == Decimal("9999999999.99")
    assert rate_edge.amount == Decimal("9999999999.99")
    assert Delivery.objects.count() == 2


def test_record_distinguishes_invalid_and_missing_crop_grade(farmer, grade):
    _price(grade, "1.00", date(2026, 1, 1))
    kwargs = {
        "farmer": farmer,
        "delivered_on": DELIVERED_ON,
        "gross_weight_kg": Decimal("1.000"),
        "moisture_percent": Decimal("14.00"),
        "clock": _frozen(date(2026, 1, 20)),
    }
    with pytest.raises(ValidationError) as invalid:
        delivery.record_delivery(crop_grade=None, **kwargs)
    assert invalid.value.code == "crop_grade_required"
    missing_grade = CropGrade(pk=99999999, crop=grade.crop, code="B")
    with pytest.raises(ServiceError) as missing:
        delivery.record_delivery(crop_grade=missing_grade, **kwargs)
    assert missing.value.code == "crop_grade_not_found"
    assert Delivery.objects.count() == 0


# --- Snapshot immutability -------------------------------------------------


def test_snapshot_is_preserved_when_a_new_price_is_added(farmer, grade):
    original = _price(grade, "24.50", date(2026, 1, 1))
    snapshot = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=DELIVERED_ON,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
    )
    frozen = {
        field: getattr(snapshot, field)
        for field in ("applied_price", "price_list_entry_id", "amount", "net_kg")
    }

    _price(grade, "10.00", date(2026, 1, 5))  # back-dated; would win a fresh lookup

    snapshot.refresh_from_db()
    assert {field: getattr(snapshot, field) for field in frozen} == frozen
    assert snapshot.price_list_entry_id == original.pk


# --- Editing ---------------------------------------------------------------


def test_edit_refreshes_the_draft_totals(farmer, grade):
    _price(grade, "24.50", date(2026, 1, 1))
    snapshot = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=DELIVERED_ON,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
    )
    draft = payouts.build_weekly_payout(farmer, WEEK_START)
    assert draft.gross_amount == Decimal("2450.00")

    delivery.edit_delivery(snapshot, gross_weight_kg=Decimal("80.000"))

    draft.refresh_from_db()
    assert draft.gross_amount == Decimal("1960.00")
    assert draft.net_amount == Decimal("1960.00")
    snapshot.refresh_from_db()
    assert snapshot.gross_weight_kg == Decimal("80.000")
    assert snapshot.amount == Decimal("1960.00")


def test_edit_preserves_the_frozen_price_when_a_new_price_is_added(farmer, grade):
    original = _price(grade, "24.50", date(2026, 1, 1))
    snapshot = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=DELIVERED_ON,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
    )
    _price(grade, "10.00", date(2026, 1, 5))

    delivery.edit_delivery(snapshot, gross_weight_kg=Decimal("50.000"))

    snapshot.refresh_from_db()
    assert snapshot.price_list_entry_id == original.pk
    assert snapshot.applied_price == Decimal("24.50")
    assert snapshot.amount == Decimal("1225.00")


def test_edit_to_a_new_date_re_resolves_the_price(farmer, grade):
    _price(grade, "24.50", date(2026, 1, 1))
    snapshot = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=DELIVERED_ON,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
    )
    newer = _price(grade, "30.00", date(2026, 1, 10))

    delivery.edit_delivery(snapshot, delivered_on=date(2026, 1, 12))

    snapshot.refresh_from_db()
    assert snapshot.accounting_date == date(2026, 1, 12)
    assert snapshot.applied_price == Decimal("30.00")
    assert snapshot.price_list_entry_id == newer.pk


def test_edit_moves_the_delivery_to_the_new_week_draft(farmer, grade):
    _price(grade, "24.50", date(2026, 1, 1))
    snapshot = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=DELIVERED_ON,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
    )
    old_draft = payouts.build_weekly_payout(farmer, WEEK_START)

    delivery.edit_delivery(snapshot, delivered_on=date(2026, 1, 13))

    snapshot.refresh_from_db()
    assert snapshot.accounting_date == date(2026, 1, 13)
    assert not Payout.objects.filter(pk=old_draft.pk).exists()
    new_draft = Payout.objects.get(farmer=farmer, week_start=NEXT_WEEK_START)
    assert snapshot.payout_id == new_draft.pk
    assert new_draft.gross_amount == Decimal("2450.00")


def test_edit_is_rejected_for_a_settled_payout(farmer, grade):
    _price(grade, "24.50", date(2026, 1, 1))
    snapshot = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=DELIVERED_ON,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
    )
    draft = payouts.build_weekly_payout(farmer, WEEK_START)
    payouts.finalise_payout(draft)

    with pytest.raises(payouts.PayoutStateError):
        delivery.edit_delivery(snapshot, gross_weight_kg=Decimal("90.000"))

    snapshot.refresh_from_db()
    assert snapshot.gross_weight_kg == Decimal("100.000")
    assert snapshot.amount == Decimal("2450.00")


def test_edit_rejects_amounts_above_the_moisture_maximum(farmer, grade):
    _price(grade, "24.50", date(2026, 1, 1))
    snapshot = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=DELIVERED_ON,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
    )

    with pytest.raises(delivery.MoistureExceedsMaximum):
        delivery.edit_delivery(snapshot, moisture_percent=Decimal("20.01"))

    snapshot.refresh_from_db()
    assert snapshot.moisture_percent == Decimal("14.00")
