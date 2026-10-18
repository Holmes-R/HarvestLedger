"""Concurrency against real PostgreSQL with independent connections.

Each worker thread opens its **own** database connection (Django connections are
thread-local) and commits its own transactions -- the ``transaction=True``
fixture is what makes those commits visible to the other threads and to the
final assertions. Nothing here relies on a process-local lock: the guarantee
under test is the PostgreSQL ``select_for_update()`` row lock taken in the
fixed order farmer -> payout -> deliveries.

Every test checks *persisted* state -- balances, membership and totals -- not
merely that the requests completed.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.db import connections

from procurement.clock import FrozenClock
from procurement.models import (
    Crop,
    CropGrade,
    Delivery,
    DeliveryKind,
    Farmer,
    Payout,
    PriceListEntry,
)

pytestmark = pytest.mark.m2

WEEK_1 = date(2026, 1, 5)  # Monday
WEEK_2 = date(2026, 1, 12)


def _frozen(business_day: date) -> FrozenClock:
    # 06:00 UTC == 11:30 IST, so the IST business date equals ``business_day``.
    return FrozenClock(
        datetime(
            business_day.year, business_day.month, business_day.day, 6, 0, tzinfo=UTC
        )
    )


def _setup(phone: str = "9000000001"):
    farmer = Farmer.objects.create(name="Asha", phone=phone, village="Kolar")
    crop = Crop.objects.create(
        name="Maize", moisture_threshold=Decimal("14.00"), max_moisture=Decimal("20.00")
    )
    grade = CropGrade.objects.create(crop=crop, code="A")
    PriceListEntry.objects.create(
        crop_grade=grade, price_per_kg=Decimal("24.50"), effective_from=date(2026, 1, 1)
    )
    return farmer, grade


def _reference_rows(farmer_id: int, grade_id: int):
    return Farmer.objects.get(pk=farmer_id), CropGrade.objects.get(pk=grade_id)


@pytest.mark.django_db(transaction=True)
def test_concurrent_deliveries_persist_every_snapshot_exactly_once():
    from procurement.services import delivery

    farmer, grade = _setup()
    workers = 6

    def record(_index):
        try:
            thread_farmer, thread_grade = _reference_rows(farmer.pk, grade.pk)
            delivery.record_delivery(
                farmer=thread_farmer,
                crop_grade=thread_grade,
                delivered_on=WEEK_1,
                gross_weight_kg=Decimal("10.000"),
                moisture_percent=Decimal("14.00"),
                clock=_frozen(WEEK_1),
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(record, range(workers)))

    rows = Delivery.objects.filter(farmer=farmer, kind=DeliveryKind.PROCUREMENT)
    assert rows.count() == workers  # none lost, none duplicated
    assert set(rows.values_list("amount", flat=True)) == {Decimal("245.00")}
    assert set(rows.values_list("applied_price", flat=True)) == {Decimal("24.50")}
    assert set(rows.values_list("net_kg", flat=True)) == {Decimal("10.00000")}


@pytest.mark.django_db(transaction=True)
def test_concurrent_finalisation_of_two_weeks_persists_both_recoveries():
    from procurement.services import advances, delivery, payouts

    farmer, grade = _setup()
    advances.post_advance(farmer, Decimal("2000.00"), WEEK_1)
    first = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=WEEK_1,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
        clock=_frozen(WEEK_1),
    )
    second = delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=WEEK_2,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
        clock=_frozen(WEEK_2),
    )
    week1 = payouts.build_weekly_payout(farmer, WEEK_1)
    week2 = payouts.build_weekly_payout(farmer, WEEK_2)

    def finalise(payout_id):
        try:
            payouts.finalise_payout(Payout.objects.get(pk=payout_id))
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(finalise, [week1.pk, week2.pk]))

    week1.refresh_from_db()
    week2.refresh_from_db()
    farmer.refresh_from_db()

    # Both weeks cap at 735.00 and the balance never drops below the cap mid-run,
    # so the result is order-independent.
    for payout in (week1, week2):
        assert payout.status == "FINALISED"
        assert payout.gross_amount == Decimal("2450.00")
        assert payout.advance_deduction == Decimal("735.00")
        assert payout.net_amount == Decimal("1715.00")
    assert farmer.outstanding_advance == Decimal("530.00")  # 2000 - 735 - 735
    assert set(week1.deliveries.values_list("pk", flat=True)) == {first.pk}
    assert set(week2.deliveries.values_list("pk", flat=True)) == {second.pk}
    assert advances.assert_outstanding_reconciles(farmer).is_reconciled


@pytest.mark.django_db(transaction=True)
def test_concurrent_recording_and_generation_converge_without_lost_deliveries():
    from procurement.services import delivery, payouts

    farmer, grade = _setup()
    workers = 5

    def record(_index):
        try:
            thread_farmer, thread_grade = _reference_rows(farmer.pk, grade.pk)
            delivery.record_delivery(
                farmer=thread_farmer,
                crop_grade=thread_grade,
                delivered_on=WEEK_1,
                gross_weight_kg=Decimal("10.000"),
                moisture_percent=Decimal("14.00"),
                clock=_frozen(WEEK_1),
            )
        finally:
            connections.close_all()

    def build(_index):
        try:
            payouts.build_weekly_payout(Farmer.objects.get(pk=farmer.pk), WEEK_1)
        finally:
            connections.close_all()

    def job(index):
        (record if index % 2 == 0 else build)(index)

    with ThreadPoolExecutor(max_workers=workers * 2) as pool:
        list(pool.map(job, range(workers * 2)))

    # A final generation attaches any delivery recorded after the last build.
    payout = payouts.build_weekly_payout(farmer, WEEK_1)

    assert Payout.objects.filter(farmer=farmer).count() == 1
    members = Delivery.objects.filter(farmer=farmer, kind=DeliveryKind.PROCUREMENT)
    assert members.count() == workers
    assert set(payout.deliveries.values_list("pk", flat=True)) == set(
        members.values_list("pk", flat=True)
    )
    assert payout.gross_amount == Decimal("10.000") * Decimal("24.50") * workers
    assert payout.gross_amount == payout.net_amount  # draft never recovers
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("0.00")
