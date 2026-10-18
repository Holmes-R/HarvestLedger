"""Independent Part 2 boundary and concurrency regressions on PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Barrier

import pytest
from django.db import connections

from procurement.clock import FrozenClock
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
from procurement.services import advances, corrections, delivery, payouts

pytestmark = pytest.mark.m2

MON = date(2026, 1, 5)
NEXT = date(2026, 1, 12)
CLOCK = FrozenClock(datetime(2026, 2, 1, 6, tzinfo=UTC))


def setup_case():
    farmer = Farmer.objects.create(
        name="Part 2 farmer", phone="9000000001", village="Test"
    )
    crop = Crop.objects.create(
        name="Part 2 crop",
        moisture_threshold=Decimal("14.00"),
        max_moisture=Decimal("20.00"),
    )
    grade = CropGrade.objects.create(crop=crop, code="A")
    PriceListEntry.objects.create(
        crop_grade=grade, effective_from=MON, price_per_kg=Decimal("1.00")
    )
    return farmer, grade


def make_delivery(farmer, grade, day=MON, gross="100.000"):
    return delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=day,
        gross_weight_kg=Decimal(gross),
        moisture_percent=Decimal("14.00"),
        clock=CLOCK,
    )


def parallel(*jobs):
    gate = Barrier(len(jobs))

    def run(job):
        try:
            gate.wait(timeout=15)
            try:
                return ("ok", job())
            except payouts.PayoutStateError as exc:
                return ("conflict", exc.code)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [pool.submit(run, job) for job in jobs]
        return [future.result(timeout=30) for future in futures]


@pytest.mark.django_db(transaction=True)
def test_w04_barrier_generation_one_draft():
    farmer, grade = setup_case()
    rows = [make_delivery(farmer, grade) for _ in range(3)]
    results = parallel(
        *[
            lambda: (
                payouts.build_weekly_payout(Farmer.objects.get(pk=farmer.pk), MON).pk
            )
            for _ in range(2)
        ]
    )
    assert all(kind == "ok" for kind, _ in results), results
    assert len({value for _, value in results}) == 1
    assert Payout.objects.filter(farmer=farmer).count() == 1
    payout = Payout.objects.get(farmer=farmer)
    assert set(payout.deliveries.values_list("pk", flat=True)) == {
        row.pk for row in rows
    }
    assert payout.gross_amount == payout.net_amount == Decimal("300.00")


@pytest.mark.django_db(transaction=True)
def test_t01_barrier_same_payout_finalised_once():
    farmer, grade = setup_case()
    advances.post_advance(farmer, Decimal("100.00"), MON)
    row = make_delivery(farmer, grade)
    draft = payouts.build_weekly_payout(farmer, MON)
    results = parallel(
        *[
            lambda: payouts.finalise_payout(Payout.objects.get(pk=draft.pk)).pk
            for _ in range(2)
        ]
    )
    assert sorted(kind for kind, _ in results) == ["conflict", "ok"], results
    draft.refresh_from_db()
    farmer.refresh_from_db()
    row.refresh_from_db()
    assert draft.status == "FINALISED"
    assert (draft.gross_amount, draft.advance_deduction, draft.net_amount) == (
        Decimal("100.00"),
        Decimal("30.00"),
        Decimal("70.00"),
    )
    assert farmer.outstanding_advance == Decimal("70.00")
    assert row.payout_id == draft.pk


@pytest.mark.django_db(transaction=True)
def test_t02_barrier_different_weeks_share_farmer_balance():
    farmer, grade = setup_case()
    advances.post_advance(farmer, Decimal("40.00"), MON)
    first = make_delivery(farmer, grade, MON)
    second = make_delivery(farmer, grade, NEXT)
    drafts = [payouts.build_weekly_payout(farmer, day) for day in (MON, NEXT)]
    results = parallel(
        *[
            lambda pk=draft.pk: payouts.finalise_payout(Payout.objects.get(pk=pk)).pk
            for draft in drafts
        ]
    )
    assert all(kind == "ok" for kind, _ in results), results
    for draft in drafts:
        draft.refresh_from_db()
    farmer.refresh_from_db()
    first.refresh_from_db()
    second.refresh_from_db()
    assert sum(draft.advance_deduction for draft in drafts) == Decimal("40.00")
    assert all(draft.advance_deduction <= Decimal("30.00") for draft in drafts)
    assert farmer.outstanding_advance == Decimal("0.00")
    assert {first.payout_id, second.payout_id} == {draft.pk for draft in drafts}


@pytest.mark.django_db(transaction=True)
def test_t03_barrier_edit_versus_finalise_serial_order():
    farmer, grade = setup_case()
    row = make_delivery(farmer, grade)
    draft = payouts.build_weekly_payout(farmer, MON)

    def edit():
        return delivery.edit_delivery(
            Delivery.objects.get(pk=row.pk),
            gross_weight_kg=Decimal("200.000"),
            clock=CLOCK,
        ).pk

    def finalise():
        return payouts.finalise_payout(Payout.objects.get(pk=draft.pk)).pk

    results = parallel(edit, finalise)
    assert sorted(kind for kind, _ in results) in (["conflict", "ok"], ["ok", "ok"]), (
        results
    )
    row.refresh_from_db()
    draft.refresh_from_db()
    farmer.refresh_from_db()
    assert draft.status == "FINALISED"
    assert row.payout_id == draft.pk
    assert draft.gross_amount == draft.net_amount == row.amount
    assert row.amount in (Decimal("100.00"), Decimal("200.00"))
    assert farmer.outstanding_advance == Decimal("0.00")
    assert (row.amount == Decimal("200.00")) == all(kind == "ok" for kind, _ in results)


@pytest.mark.django_db(transaction=True)
def test_t03_barrier_advance_versus_finalise_serial_order():
    farmer, grade = setup_case()
    row = make_delivery(farmer, grade)
    draft = payouts.build_weekly_payout(farmer, MON)
    results = parallel(
        lambda: (
            advances.post_advance(
                Farmer.objects.get(pk=farmer.pk), Decimal("50.00"), MON
            ).pk
        ),
        lambda: payouts.finalise_payout(Payout.objects.get(pk=draft.pk)).pk,
    )
    assert all(kind == "ok" for kind, _ in results), results
    farmer.refresh_from_db()
    draft.refresh_from_db()
    row.refresh_from_db()
    assert Advance.objects.filter(farmer=farmer).count() == 1
    assert draft.status == "FINALISED" and row.payout_id == draft.pk
    assert draft.gross_amount == Decimal("100.00")
    assert draft.advance_deduction in (Decimal("0.00"), Decimal("30.00"))
    assert draft.net_amount == draft.gross_amount - draft.advance_deduction
    assert farmer.outstanding_advance == Decimal("50.00") - draft.advance_deduction
    assert advances.assert_outstanding_reconciles(farmer).is_reconciled


@pytest.mark.django_db(transaction=True)
def test_t04_failure_after_balance_save_rolls_back_all(monkeypatch):
    farmer, grade = setup_case()
    advances.post_advance(farmer, Decimal("50.00"), MON)
    row = make_delivery(farmer, grade)
    draft = payouts.build_weekly_payout(farmer, MON)
    original_save = Farmer.save

    def save_then_fail(self, *args, **kwargs):
        original_save(self, *args, **kwargs)
        raise RuntimeError("injected after balance write")

    monkeypatch.setattr(Farmer, "save", save_then_fail)
    with pytest.raises(RuntimeError, match="after balance write"):
        payouts.finalise_payout(draft)
    farmer.refresh_from_db()
    draft.refresh_from_db()
    row.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("50.00")
    assert draft.status == "DRAFT" and draft.finalised_at is None
    assert (draft.gross_amount, draft.advance_deduction, draft.net_amount) == (
        Decimal("100.00"),
        Decimal("0.00"),
        Decimal("100.00"),
    )
    assert row.payout_id == draft.pk


@pytest.mark.django_db(transaction=True)
def test_w02_empty_week_returns_none_and_preserves_balance():
    farmer, _ = setup_case()
    result = payouts.build_weekly_payout(farmer, MON)
    assert Payout.objects.count() == 0
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("0.00")
    assert result is None


@pytest.mark.django_db(transaction=True)
def test_a04_round_down_cap():
    farmer, grade = setup_case()
    advances.post_advance(farmer, Decimal("100.00"), MON)
    row = make_delivery(farmer, grade, gross="100.050")
    draft = payouts.build_weekly_payout(farmer, MON)
    payouts.finalise_payout(draft)
    draft.refresh_from_db()
    row.refresh_from_db()
    farmer.refresh_from_db()
    assert row.amount == draft.gross_amount == Decimal("100.05")
    assert (draft.advance_deduction, draft.net_amount, farmer.outstanding_advance) == (
        Decimal("30.01"),
        Decimal("70.04"),
        Decimal("69.99"),
    )


@pytest.mark.django_db(transaction=True)
def test_c02_forged_original_farmer_is_ignored():
    farmer, grade = setup_case()
    other = Farmer.objects.create(name="Other", phone="9000000002", village="Test")
    original = make_delivery(farmer, grade)
    draft = payouts.build_weekly_payout(farmer, MON)
    payouts.finalise_payout(draft)
    original.refresh_from_db()
    original.farmer_id = (
        other.pk
    )  # client-side instance mutation; database row remains farmer's
    note = corrections.record_correction(
        original, DeliveryKind.CREDIT_NOTE, Decimal("10.00"), "check", clock=CLOCK
    )
    stored_original = Delivery.objects.get(pk=original.pk)
    stored_note = Delivery.objects.get(pk=note.pk)
    assert stored_original.farmer_id == farmer.pk
    assert stored_note.original_delivery_id == original.pk
    assert stored_note.farmer_id == stored_original.farmer_id


@pytest.mark.django_db(transaction=True)
def test_w01_sunday_next_monday_and_farmer_exclusion():
    farmer, grade = setup_case()
    other = Farmer.objects.create(name="Other", phone="9000000002", village="Test")
    sunday = make_delivery(farmer, grade, date(2026, 1, 11))
    monday = make_delivery(farmer, grade, NEXT)
    other_row = make_delivery(other, grade, date(2026, 1, 11))
    first = payouts.build_weekly_payout(farmer, MON)
    second = payouts.build_weekly_payout(farmer, NEXT)
    assert (first.week_start, first.week_end) == (MON, date(2026, 1, 11))
    assert (second.week_start, second.week_end) == (NEXT, date(2026, 1, 18))
    assert set(first.deliveries.values_list("pk", flat=True)) == {sunday.pk}
    assert set(second.deliveries.values_list("pk", flat=True)) == {monday.pk}
    assert other_row.payout_id is None
    assert sunday.accounting_date == date(2026, 1, 11)
    assert monday.accounting_date == NEXT


@pytest.mark.django_db(transaction=True)
def test_i02_paid_statement_rejects_delivery_edit():
    farmer, grade = setup_case()
    row = make_delivery(farmer, grade)
    payout = payouts.build_weekly_payout(farmer, MON)
    payouts.finalise_payout(payout)
    paid = payouts.mark_payout_paid(payout)
    row.refresh_from_db()
    frozen = (
        paid.gross_amount,
        paid.advance_deduction,
        paid.net_amount,
        paid.finalised_at,
        row.amount,
        row.payout_id,
    )
    with pytest.raises(payouts.PayoutStateError):
        delivery.edit_delivery(row, gross_weight_kg=Decimal("200.000"), clock=CLOCK)
    paid.refresh_from_db()
    row.refresh_from_db()
    assert paid.status == "PAID"
    assert (
        paid.gross_amount,
        paid.advance_deduction,
        paid.net_amount,
        paid.finalised_at,
        row.amount,
        row.payout_id,
    ) == frozen


@pytest.mark.django_db(transaction=True)
def test_c04_zero_gross_preserves_zero_net_and_advance():
    farmer, grade = setup_case()
    advances.post_advance(farmer, Decimal("50.00"), MON)
    original = make_delivery(farmer, grade, MON)
    first = payouts.build_weekly_payout(farmer, MON)
    payouts.finalise_payout(first)
    original.refresh_from_db()
    make_delivery(farmer, grade, NEXT)
    note = corrections.record_correction(
        original,
        DeliveryKind.DEBIT_NOTE,
        Decimal("100.00"),
        "check",
        clock=FrozenClock(datetime(2026, 1, 12, 6, tzinfo=UTC)),
    )
    second = payouts.build_weekly_payout(farmer, NEXT)
    assert set(second.deliveries.values_list("pk", flat=True)) == {
        note.pk,
        Delivery.objects.get(
            farmer=farmer, accounting_date=NEXT, kind=DeliveryKind.PROCUREMENT
        ).pk,
    }
    balance_before = Farmer.objects.get(pk=farmer.pk).outstanding_advance
    payouts.finalise_payout(second)
    second.refresh_from_db()
    farmer.refresh_from_db()
    assert (second.gross_amount, second.advance_deduction, second.net_amount) == (
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    )
    assert farmer.outstanding_advance == balance_before
