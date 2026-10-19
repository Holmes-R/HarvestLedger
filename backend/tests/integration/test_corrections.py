"""Credit/debit note corrections.

M1 model constraints (a note must reference an original delivery, carry a
positive magnitude and a non-blank reason) run first; the M2 service layer
(marker ``m2``) is then exercised for farmer inheritance, credit/debit sign,
business-date stamping and inclusion in the next eligible payout.

Contract exercised
------------------
``procurement.services.corrections.record_correction(
    original_delivery, kind, magnitude, reason) -> Delivery`` -- creates a
CREDIT_NOTE (+) or DEBIT_NOTE (-) correction against ``original_delivery``,
inheriting its farmer and stamping ``accounting_date`` with the IST business
date (``procurement.clock.get_clock().today()``). The signed amount flows into
that date's weekly payout.
"""

from datetime import UTC, date, datetime, timedelta
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


@pytest.mark.m2
def test_correction_magnitude_exceeding_field_capacity_is_atomic(farmer, grade):
    from procurement.services import corrections

    original, payout = _finalised_original(farmer, grade)
    before = Delivery.objects.count()
    with pytest.raises(ValidationError) as error:
        corrections.record_correction(
            original, DeliveryKind.CREDIT_NOTE, Decimal("1000000000000.00"), "review"
        )
    assert error.value.code == "max_whole_digits"
    original.refresh_from_db()
    payout.refresh_from_db()
    assert Delivery.objects.count() == before
    assert original.amount == payout.gross_amount == Decimal("2450.00")


@pytest.mark.m2
def test_correction_uses_persisted_original_farmer_and_snapshot(farmer, grade):
    from procurement.services import corrections

    original, payout = _finalised_original(farmer, grade)
    other = Farmer.objects.create(name="Bina", phone="9000000002", village="Kolar")
    original.farmer_id = other.pk
    original.amount = Decimal("1.00")
    original.payout = payout

    note = corrections.record_correction(
        original, DeliveryKind.CREDIT_NOTE, Decimal("10.00"), "review"
    )
    stored_original = Delivery.objects.get(pk=original.pk)
    stored_note = Delivery.objects.get(pk=note.pk)
    assert stored_original.farmer_id == farmer.pk
    assert stored_original.amount == Decimal("2450.00")
    assert stored_note.original_delivery_id == stored_original.pk
    assert stored_note.farmer_id == stored_original.farmer_id
    assert stored_note.amount == Decimal("10.00")
    assert not Delivery.objects.filter(
        original_delivery=stored_original, farmer=other
    ).exists()


@pytest.mark.m2
def test_correction_rejects_stale_payout_state_without_partial_write(farmer, grade):
    from procurement.services import corrections

    original = _procurement(farmer, grade)
    settled = Payout.objects.create(
        farmer=farmer,
        week_start=WEEK_START,
        week_end=date(2026, 1, 11),
        status=PayoutStatus.FINALISED,
        gross_amount=Decimal("2450.00"),
        net_amount=Decimal("2450.00"),
    )
    original.payout = settled  # A caller changed only this in-memory instance.
    before = Delivery.objects.count()
    with pytest.raises(ValidationError) as error:
        corrections.record_correction(
            original, DeliveryKind.DEBIT_NOTE, Decimal("10.00"), "review"
        )
    assert error.value.code == "original_not_settled"
    assert Delivery.objects.count() == before
    assert Delivery.objects.get(pk=original.pk).payout_id is None


@pytest.mark.m2
def test_correction_rejects_missing_original_id_without_partial_write(farmer):
    from procurement.services import corrections

    missing = Delivery(pk=999999999, farmer=farmer, kind=DeliveryKind.PROCUREMENT)
    before = Delivery.objects.count()
    with pytest.raises(corrections.OriginalDeliveryNotFound) as error:
        corrections.record_correction(
            missing, DeliveryKind.CREDIT_NOTE, Decimal("10.00"), "review"
        )
    assert error.value.code == "original_not_found"
    assert Delivery.objects.count() == before


@pytest.mark.django_db(transaction=True)
@pytest.mark.m2
def test_correction_rechecks_ownership_after_farmer_lock(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from django.db import connections

    from procurement.services import corrections

    farmer = Farmer.objects.create(name="Asha", phone="9000000001", village="Kolar")
    other = Farmer.objects.create(name="Bina", phone="9000000002", village="Kolar")
    crop = Crop.objects.create(
        name="Maize", moisture_threshold=Decimal("14.00"), max_moisture=Decimal("20.00")
    )
    grade = CropGrade.objects.create(crop=crop, code="A")
    original, payout = _finalised_original(farmer, grade)
    reached_lock = Event()
    allow_lock = Event()
    real_lock = corrections.lock_farmer

    def pause_before_lock(farmer_id):
        reached_lock.set()
        if not allow_lock.wait(10):
            raise TimeoutError("the ownership-change worker did not proceed")
        return real_lock(farmer_id)

    monkeypatch.setattr(corrections, "lock_farmer", pause_before_lock)

    def create_note():
        try:
            corrections.record_correction(
                original, DeliveryKind.CREDIT_NOTE, Decimal("10.00"), "review"
            )
        except ValidationError as error:
            return error.code
        finally:
            connections.close_all()
        return "unexpected_write"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(create_note)
        try:
            assert reached_lock.wait(10)
            Delivery.objects.filter(pk=original.pk).update(farmer=other)
        finally:
            allow_lock.set()
        outcome = future.result(timeout=20)

    assert outcome == "original_changed"
    assert Delivery.objects.get(pk=original.pk).farmer_id == other.pk
    assert not Delivery.objects.filter(original_delivery_id=original.pk).exists()
    assert Payout.objects.get(pk=payout.pk).farmer_id == farmer.pk


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


# --- M2 service rules ------------------------------------------------------


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


# --- Original requirement, inputs and signs --------------------------------


@pytest.mark.m2
def test_correction_requires_an_existing_original(farmer):
    from procurement.services import corrections

    with pytest.raises(ValidationError) as excinfo:
        corrections.record_correction(
            original_delivery=None,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal("10.00"),
            reason="weight re-check",
        )
    assert excinfo.value.code == "original_required"


@pytest.mark.m2
def test_correction_rejects_an_unsaved_original(farmer):
    from procurement.services import corrections

    unsaved = Delivery(farmer=farmer, kind=DeliveryKind.PROCUREMENT)
    with pytest.raises(ValidationError) as excinfo:
        corrections.record_correction(
            original_delivery=unsaved,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal("10.00"),
            reason="weight re-check",
        )
    assert excinfo.value.code == "original_required"


@pytest.mark.m2
def test_correction_inherits_the_originals_farmer(farmer, grade):
    from procurement.services import corrections

    other = Farmer.objects.create(name="Bina", phone="9000000002", village="Kolar")
    original, _ = _finalised_original(other, grade)

    note = corrections.record_correction(
        original_delivery=original,
        kind=DeliveryKind.CREDIT_NOTE,
        magnitude=Decimal("10.00"),
        reason="weight re-check",
    )

    assert note.farmer_id == other.pk
    assert note.farmer_id != farmer.pk


@pytest.mark.m2
@pytest.mark.parametrize("kind", [DeliveryKind.PROCUREMENT, "SOMETHING_ELSE", None, ""])
def test_invalid_correction_kind_is_rejected(farmer, grade, kind):
    from procurement.services import corrections

    original, _ = _finalised_original(farmer, grade)
    with pytest.raises(ValidationError) as excinfo:
        corrections.record_correction(
            original_delivery=original,
            kind=kind,
            magnitude=Decimal("10.00"),
            reason="weight re-check",
        )
    assert excinfo.value.code == "invalid_kind"
    assert not Delivery.objects.filter(original_delivery=original).exists()


@pytest.mark.m2
@pytest.mark.parametrize("magnitude", ["0.00", "-5.00"])
def test_nonpositive_magnitude_is_rejected(farmer, grade, magnitude):
    from procurement.services import corrections

    original, _ = _finalised_original(farmer, grade)
    with pytest.raises(ValidationError) as excinfo:
        corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal(magnitude),
            reason="weight re-check",
        )
    assert excinfo.value.code == "not_positive"
    assert not Delivery.objects.filter(original_delivery=original).exists()


@pytest.mark.m2
def test_overprecise_magnitude_is_rejected(farmer, grade):
    from procurement.services import corrections

    original, _ = _finalised_original(farmer, grade)
    with pytest.raises(ValidationError) as excinfo:
        corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal("10.001"),
            reason="weight re-check",
        )
    assert excinfo.value.code == "too_many_decimal_places"
    assert not Delivery.objects.filter(original_delivery=original).exists()


@pytest.mark.m2
@pytest.mark.parametrize("reason", ["", "   ", "\t"])
def test_blank_reason_is_rejected(farmer, grade, reason):
    from procurement.services import corrections

    original, _ = _finalised_original(farmer, grade)
    with pytest.raises(ValidationError) as excinfo:
        corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal("10.00"),
            reason=reason,
        )
    assert excinfo.value.code == "reason_required"
    assert not Delivery.objects.filter(original_delivery=original).exists()


@pytest.mark.m2
@pytest.mark.parametrize(
    ("kind", "expected_amount"),
    [
        (DeliveryKind.CREDIT_NOTE, "50.00"),
        (DeliveryKind.DEBIT_NOTE, "-50.00"),
    ],
)
def test_signed_amount_matches_the_kind(farmer, grade, kind, expected_amount):
    from procurement.services import corrections

    original, _ = _finalised_original(farmer, grade)
    note = corrections.record_correction(
        original_delivery=original,
        kind=kind,
        magnitude=Decimal("50.00"),
        reason="weight re-check",
    )

    assert note.kind == kind
    assert note.amount == Decimal(expected_amount)
    assert note.correction_magnitude == Decimal("50.00")


# --- Accounting date / week membership -------------------------------------


@pytest.mark.m2
def test_correction_week_follows_the_accounting_date(farmer, grade):
    from procurement.services import corrections, payouts

    original, first = _finalised_original(farmer, grade)  # WEEK_1 is finalised
    note = corrections.record_correction(
        original_delivery=original,
        kind=DeliveryKind.CREDIT_NOTE,
        magnitude=Decimal("50.00"),
        reason="late correction",
        clock=_frozen(NEXT_WEEK_START),  # Monday opens WEEK_2
    )

    assert note.accounting_date == NEXT_WEEK_START
    week2 = payouts.build_weekly_payout(farmer, NEXT_WEEK_START)
    assert week2.pk != first.pk
    assert set(week2.deliveries.values_list("pk", flat=True)) == {note.pk}


@pytest.mark.m2
def test_correction_on_a_sunday_joins_that_weeks_payout(farmer, grade):
    from procurement.services import corrections, payouts

    original, first = _finalised_original(farmer, grade)
    sunday = date(2026, 1, 11)  # WEEK_1 Sunday
    note = corrections.record_correction(
        original_delivery=original,
        kind=DeliveryKind.DEBIT_NOTE,
        magnitude=Decimal("20.00"),
        reason="late correction",
        clock=_frozen(sunday),
    )

    assert note.accounting_date == sunday
    supplementary = payouts.build_weekly_payout(farmer, sunday)
    assert supplementary.pk != first.pk  # WEEK_1 already finalised
    assert set(supplementary.deliveries.values_list("pk", flat=True)) == {note.pk}


@pytest.mark.m2
def test_multiple_corrections_may_reference_one_original(farmer, grade):
    from procurement.services import corrections, payouts

    original, _ = _finalised_original(farmer, grade)
    with use_clock(_frozen(NEXT_WEEK_START)):
        credit = corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal("50.00"),
            reason="weight under-counted",
        )
        debit = corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.DEBIT_NOTE,
            magnitude=Decimal("20.00"),
            reason="rate corrected",
        )
        payout = payouts.build_weekly_payout(farmer, NEXT_WEEK_START)

    assert credit.pk != debit.pk
    assert credit.original_delivery_id == debit.original_delivery_id == original.pk
    assert set(payout.deliveries.values_list("pk", flat=True)) == {credit.pk, debit.pk}
    assert payout.gross_amount == Decimal("30.00")


@pytest.mark.m2
def test_correction_enters_exactly_one_payout(farmer, grade):
    from procurement.services import corrections, payouts

    original, _ = _finalised_original(farmer, grade)
    with use_clock(_frozen(NEXT_WEEK_START)):
        note = corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal("50.00"),
            reason="weight re-check",
        )
        week2 = payouts.build_weekly_payout(farmer, NEXT_WEEK_START)
        again = payouts.build_weekly_payout(farmer, NEXT_WEEK_START)
        week3 = payouts.build_weekly_payout(
            farmer, NEXT_WEEK_START + timedelta(weeks=1)
        )

    note.refresh_from_db()
    assert note.payout_id == week2.pk == again.pk
    assert week3 is None


@pytest.mark.m2
def test_correction_leaves_the_finalised_statement_unchanged(farmer, grade):
    from procurement.services import corrections

    original, original_payout = _finalised_original(farmer, grade)
    statement = (
        original_payout.status,
        original_payout.gross_amount,
        original_payout.advance_deduction,
        original_payout.net_amount,
        original_payout.finalised_at,
    )

    with use_clock(_frozen(NEXT_WEEK_START)):
        corrections.record_correction(
            original_delivery=original,
            kind=DeliveryKind.CREDIT_NOTE,
            magnitude=Decimal("50.00"),
            reason="weight re-check",
        )

    original_payout.refresh_from_db()
    original.refresh_from_db()
    assert (
        original_payout.status,
        original_payout.gross_amount,
        original_payout.advance_deduction,
        original_payout.net_amount,
        original_payout.finalised_at,
    ) == statement
    assert original.payout_id == original_payout.pk


@pytest.mark.m2
def test_debit_only_week_is_nonpositive_and_payable_without_recovery(farmer, grade):
    from procurement.services import advances, corrections, payouts

    advances.post_advance(farmer, Decimal("500.00"), WEEK_START)
    original, _ = _finalised_original(farmer, grade)
    corrections.record_correction(
        original_delivery=original,
        kind=DeliveryKind.DEBIT_NOTE,
        magnitude=Decimal("100.00"),
        reason="rate corrected",
        clock=_frozen(NEXT_WEEK_START),
    )

    payout = payouts.build_weekly_payout(farmer, NEXT_WEEK_START)
    payouts.finalise_payout(payout)
    payout.refresh_from_db()
    farmer.refresh_from_db()

    assert payout.gross_amount == Decimal("-100.00")
    assert payout.advance_deduction == Decimal("0.00")
    assert payout.net_amount == Decimal("-100.00")
    outstanding = farmer.outstanding_advance

    paid = payouts.mark_payout_paid(payout)
    farmer.refresh_from_db()
    assert paid.status == PayoutStatus.PAID
    assert farmer.outstanding_advance == outstanding


@pytest.mark.django_db(transaction=True)
@pytest.mark.m2
def test_concurrent_correction_inclusion_assigns_the_note_once():
    from concurrent.futures import ThreadPoolExecutor

    from django.db import connections

    from procurement.services import corrections, payouts

    farmer = Farmer.objects.create(name="Asha", phone="9000000001", village="Kolar")
    crop = Crop.objects.create(
        name="Maize", moisture_threshold=Decimal("14.00"), max_moisture=Decimal("20.00")
    )
    grade = CropGrade.objects.create(crop=crop, code="A")
    original, _ = _finalised_original(farmer, grade)
    note = corrections.record_correction(
        original_delivery=original,
        kind=DeliveryKind.CREDIT_NOTE,
        magnitude=Decimal("50.00"),
        reason="weight re-check",
        clock=_frozen(NEXT_WEEK_START),
    )

    def build(_index):
        try:
            payouts.build_weekly_payout(
                Farmer.objects.get(pk=farmer.pk), NEXT_WEEK_START
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(build, range(6)))

    assert Payout.objects.filter(farmer=farmer, week_start=NEXT_WEEK_START).count() == 1
    draft = Payout.objects.get(farmer=farmer, week_start=NEXT_WEEK_START)
    assert set(draft.deliveries.values_list("pk", flat=True)) == {note.pk}
