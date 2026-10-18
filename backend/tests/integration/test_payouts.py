"""Payout grouping, advance recovery and finalisation rules.

Model-level behaviour (one Draft per farmer/week, single delivery membership) is
enforced at M1. The remaining cases exercise the implemented M2 service layer
(marker ``m2``).

Contract exercised
------------------
``procurement.services.payouts.build_weekly_payout(farmer, week_start) ->
Payout | None`` -- creates/extends the DRAFT payout for the Monday-Sunday week,
attaching that farmer's unassigned deliveries in ``[week_start, week_start+6]``;
returns ``None`` when the week has no eligible deliveries.

``procurement.services.payouts.finalise_payout(payout) -> Payout`` -- sets
FINALISED, computes ``advance_deduction = min(outstanding_advance, 30% of
gross_amount)``, reduces the farmer's balance once, and freezes the payout.
``PayoutStateError`` is raised for illegal transitions (re-finalising a payout,
re-building a finalised week).

``procurement.services.payouts.mark_payout_paid(payout) -> Payout`` -- the only
approved settlement transition, FINALISED -> PAID; preserves the frozen amounts
and never recovers the advance again. ``PayoutStateError`` is raised for a DRAFT
or an already-PAID payout.

``procurement.services.advances.post_advance(farmer, amount, given_on)`` --
increases the farmer's outstanding balance.

``procurement.services.delivery.record_delivery(...)`` -- freezes a delivery.
"""

from datetime import date, timedelta
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

WEEK_1_START = date(2026, 1, 5)  # Monday
WEEK_1_END = date(2026, 1, 11)  # Sunday
WEEK_2_START = date(2026, 1, 12)


@pytest.fixture
def farmer(db):
    return Farmer.objects.create(name="Asha", phone="9000000001", village="Kolar")


@pytest.fixture
def grade(db):
    crop = Crop.objects.create(
        name="Maize", moisture_threshold=Decimal("14.00"), max_moisture=Decimal("20.00")
    )
    result = CropGrade.objects.create(crop=crop, code="A")
    PriceListEntry.objects.create(
        crop_grade=result,
        price_per_kg=Decimal("24.50"),
        effective_from=date(2026, 1, 1),
    )
    return result


def _record_delivery(farmer, grade, delivered_on, gross="100.000", moisture="14.00"):
    from procurement.services import delivery

    return delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=delivered_on,
        gross_weight_kg=Decimal(gross),
        moisture_percent=Decimal(moisture),
    )


def _model_delivery(
    farmer, grade, accounting_date, price=Decimal("24.50"), amount=Decimal("2450.00")
):
    return Delivery.objects.create(
        farmer=farmer,
        kind=DeliveryKind.PROCUREMENT,
        crop_grade=grade,
        delivered_on=accounting_date,
        accounting_date=accounting_date,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
        applied_price=price,
        amount=amount,
    )


# --- M1 model-level rules (pass at M1) -------------------------------------


def test_one_draft_payout_per_farmer_week(farmer):
    Payout.objects.create(farmer=farmer, week_start=WEEK_1_START, week_end=WEEK_1_END)
    with pytest.raises(IntegrityError), transaction.atomic():
        Payout.objects.create(
            farmer=farmer, week_start=WEEK_1_START, week_end=WEEK_1_END
        )


def test_delivery_membership_is_a_single_foreign_key(farmer, grade):
    first = Payout.objects.create(
        farmer=farmer, week_start=WEEK_1_START, week_end=WEEK_1_END
    )
    second = Payout.objects.create(
        farmer=farmer, week_start=WEEK_2_START, week_end=date(2026, 1, 18)
    )
    delivery = _model_delivery(farmer, grade, WEEK_1_START)
    delivery.payout = first
    delivery.save(update_fields=["payout"])
    delivery.refresh_from_db()

    assert delivery.payout_id == first.pk
    assert set(first.deliveries.values_list("pk", flat=True)) == {delivery.pk}
    assert not second.deliveries.filter(pk=delivery.pk).exists()


# --- M2 rule tests ----------------------------------------------------------


@pytest.mark.m2
def test_monday_to_sunday_selection(farmer, grade):
    from procurement.services import payouts

    inside_mon = _record_delivery(farmer, grade, WEEK_1_START)
    inside_sun = _record_delivery(farmer, grade, WEEK_1_END)
    before = _record_delivery(farmer, grade, date(2026, 1, 4))
    after = _record_delivery(farmer, grade, WEEK_2_START)
    other_farmer = Farmer.objects.create(
        name="Bina", phone="9000000002", village="Kolar"
    )
    someone_else = _record_delivery(other_farmer, grade, WEEK_1_START)

    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)

    ids = set(payout.deliveries.values_list("pk", flat=True))
    assert ids == {inside_mon.pk, inside_sun.pk}
    assert payout.farmer_id == farmer.pk
    assert {before.pk, after.pk, someone_else.pk}.isdisjoint(ids)


@pytest.mark.m2
def test_generation_assigns_each_delivery_once(farmer, grade):
    from procurement.services import payouts

    delivery = _record_delivery(farmer, grade, WEEK_1_START)
    first = payouts.build_weekly_payout(farmer, WEEK_1_START)
    second = payouts.build_weekly_payout(farmer, WEEK_1_START)

    delivery.refresh_from_db()
    assert first.pk == second.pk == delivery.payout_id
    assert set(second.deliveries.values_list("pk", flat=True)) == {delivery.pk}
    assert Payout.objects.filter(farmer=farmer).count() == 1


@pytest.mark.m2
def test_draft_payout_does_not_reduce_outstanding(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("1000.00"), WEEK_1_START)
    _record_delivery(farmer, grade, WEEK_1_START)
    payouts.build_weekly_payout(farmer, WEEK_1_START)

    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("1000.00")


@pytest.mark.m2
def test_recovery_cap_and_outstanding_carries_across_weeks(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("1000.00"), WEEK_1_START)

    # Week 1: 100.000 kg * 24.50 = 2450.00 gross; 30% = 735.00 -> deduct 735.00.
    _record_delivery(farmer, grade, WEEK_1_START)
    week1 = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(week1)
    farmer.refresh_from_db()
    assert week1.advance_deduction == Decimal("735.00")
    assert farmer.outstanding_advance == Decimal("265.00")

    # Week 2: 30% of 2450.00 = 735.00, but only 265.00 outstanding remains.
    _record_delivery(farmer, grade, WEEK_2_START)
    week2 = payouts.build_weekly_payout(farmer, WEEK_2_START)
    payouts.finalise_payout(week2)
    farmer.refresh_from_db()
    assert week2.advance_deduction == Decimal("265.00")
    assert farmer.outstanding_advance == Decimal("0.00")


@pytest.mark.m2
def test_large_outstanding_advance_carries_beyond_two_weeks(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("3000.00"), WEEK_1_START)
    for week_start, expected_balance in (
        (WEEK_1_START, Decimal("2265.00")),
        (WEEK_2_START, Decimal("1530.00")),
    ):
        _record_delivery(farmer, grade, week_start)
        payout = payouts.build_weekly_payout(farmer, week_start)
        payouts.finalise_payout(payout)
        payout.refresh_from_db()
        farmer.refresh_from_db()
        assert payout.advance_deduction == Decimal("735.00")
        assert farmer.outstanding_advance == expected_balance


@pytest.mark.m2
def test_recovery_cap_rounds_an_exact_half_cent_up(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("1.00"), WEEK_1_START)
    delivery = _record_delivery(farmer, grade, WEEK_1_START, gross="0.002")
    assert delivery.amount == Decimal("0.05")

    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(payout)
    payout.refresh_from_db()
    farmer.refresh_from_db()
    assert payout.gross_amount == Decimal("0.05")
    assert payout.advance_deduction == Decimal("0.02")
    assert payout.net_amount == Decimal("0.03")
    assert farmer.outstanding_advance == Decimal("0.98")


@pytest.mark.m2
def test_finalisation_changes_balance_exactly_once(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("500.00"), WEEK_1_START)
    _record_delivery(farmer, grade, WEEK_1_START)
    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)

    payouts.finalise_payout(payout)
    farmer.refresh_from_db()
    after_first = farmer.outstanding_advance

    with pytest.raises(payouts.PayoutStateError):
        payouts.finalise_payout(payout)

    farmer.refresh_from_db()
    assert farmer.outstanding_advance == after_first


@pytest.mark.m2
def test_finalised_payout_is_immutable(farmer, grade):
    from procurement.services import payouts

    _record_delivery(farmer, grade, WEEK_1_START)
    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(payout)
    payout.refresh_from_db()
    frozen = (
        payout.status,
        payout.gross_amount,
        payout.advance_deduction,
        payout.net_amount,
        set(payout.deliveries.values_list("pk", flat=True)),
    )

    with pytest.raises(payouts.PayoutStateError):
        payouts.build_weekly_payout(farmer, WEEK_1_START)
    payout.refresh_from_db()
    assert (
        payout.status,
        payout.gross_amount,
        payout.advance_deduction,
        payout.net_amount,
        set(payout.deliveries.values_list("pk", flat=True)),
    ) == frozen


@pytest.mark.m2
def test_empty_week_creates_no_payout(farmer):
    from procurement.services import payouts

    assert payouts.build_weekly_payout(farmer, WEEK_1_START) is None
    assert Payout.objects.filter(farmer=farmer).count() == 0


@pytest.mark.m2
def test_monetary_identities(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("400.00"), WEEK_1_START)
    _record_delivery(farmer, grade, WEEK_1_START)
    _record_delivery(farmer, grade, WEEK_1_END)

    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(payout)
    payout.refresh_from_db()

    gross = sum(d.amount for d in payout.deliveries.all())
    assert payout.gross_amount == gross
    assert payout.advance_deduction == min(Decimal("400.00"), Decimal("0.30") * gross)
    assert payout.net_amount == payout.gross_amount - payout.advance_deduction


@pytest.mark.m2
def test_supplementary_payout_allowed_after_finalisation(farmer, grade):
    from procurement.services import payouts

    _record_delivery(farmer, grade, WEEK_1_START)
    first = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(first)

    late = _record_delivery(farmer, grade, WEEK_1_END)
    supplementary = payouts.build_weekly_payout(farmer, WEEK_1_START)

    assert supplementary.pk != first.pk
    assert supplementary.status == PayoutStatus.DRAFT
    assert set(supplementary.deliveries.values_list("pk", flat=True)) == {late.pk}
    first.refresh_from_db()
    assert first.status == PayoutStatus.FINALISED
    assert late.pk not in set(first.deliveries.values_list("pk", flat=True))


@pytest.mark.m2
def test_no_advance_means_zero_deduction(farmer, grade):
    from procurement.services import payouts

    _record_delivery(farmer, grade, WEEK_1_START)
    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(payout)

    assert payout.advance_deduction == Decimal("0.00")
    assert payout.net_amount == payout.gross_amount


# --- Draft generation: normalization, exclusivity, refresh, concurrency ----


@pytest.mark.m2
def test_week_is_normalized_to_monday(farmer, grade):
    from procurement.services import payouts

    inside = _record_delivery(farmer, grade, date(2026, 1, 7))  # Wednesday

    payout = payouts.build_weekly_payout(farmer, date(2026, 1, 7))
    assert payout.week_start == WEEK_1_START
    assert payout.week_end == WEEK_1_END
    assert set(payout.deliveries.values_list("pk", flat=True)) == {inside.pk}

    # Any other day in the same week reuses the same DRAFT.
    again = payouts.build_weekly_payout(farmer, date(2026, 1, 10))  # Saturday
    assert again.pk == payout.pk
    assert Payout.objects.filter(farmer=farmer).count() == 1


@pytest.mark.m2
def test_adjacent_weeks_and_other_farmers_are_excluded(farmer, grade):
    from procurement.services import payouts

    inside = _record_delivery(farmer, grade, WEEK_1_END)  # Sunday
    _record_delivery(farmer, grade, date(2026, 1, 4))  # previous Sunday
    _record_delivery(farmer, grade, WEEK_2_START)  # next Monday
    other_farmer = Farmer.objects.create(
        name="Bina", phone="9000000002", village="Kolar"
    )
    _record_delivery(other_farmer, grade, WEEK_1_START)

    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    assert set(payout.deliveries.values_list("pk", flat=True)) == {inside.pk}


@pytest.mark.m2
def test_records_already_in_a_payout_are_not_reassigned(farmer, grade):
    from procurement.services import payouts

    delivery = _record_delivery(farmer, grade, WEEK_1_START)
    existing = Payout.objects.create(
        farmer=farmer, week_start=WEEK_1_START, week_end=WEEK_1_END
    )
    delivery.payout = existing
    delivery.save(update_fields=["payout"])

    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    assert payout.pk == existing.pk
    assert set(payout.deliveries.values_list("pk", flat=True)) == {delivery.pk}
    assert Payout.objects.filter(farmer=farmer).count() == 1


@pytest.mark.m2
def test_repeated_generation_does_not_duplicate_and_refreshes_membership(farmer, grade):
    from procurement.services import payouts

    first_delivery = _record_delivery(farmer, grade, WEEK_1_START)
    draft = payouts.build_weekly_payout(farmer, WEEK_1_START)
    assert draft.gross_amount == Decimal("2450.00")

    late = _record_delivery(farmer, grade, WEEK_1_END)
    again = payouts.build_weekly_payout(farmer, WEEK_1_START)

    assert again.pk == draft.pk
    assert Payout.objects.filter(farmer=farmer).count() == 1
    assert set(again.deliveries.values_list("pk", flat=True)) == {
        first_delivery.pk,
        late.pk,
    }
    assert again.gross_amount == Decimal("4900.00")
    assert again.net_amount == Decimal("4900.00")


@pytest.mark.m2
def test_generation_refreshes_stale_draft_totals(farmer, grade):
    from procurement.services import payouts

    _record_delivery(farmer, grade, WEEK_1_START)
    draft = payouts.build_weekly_payout(farmer, WEEK_1_START)
    Payout.objects.filter(pk=draft.pk).update(
        gross_amount=Decimal("1.00"), net_amount=Decimal("1.00")
    )

    refreshed = payouts.build_weekly_payout(farmer, WEEK_1_START)
    assert refreshed.gross_amount == Decimal("2450.00")
    assert refreshed.net_amount == Decimal("2450.00")


@pytest.mark.m2
def test_empty_week_creates_no_payout_for_any_day_in_the_week(farmer):
    from procurement.services import payouts

    assert payouts.build_weekly_payout(farmer, date(2026, 1, 8)) is None
    assert Payout.objects.filter(farmer=farmer).count() == 0


@pytest.mark.m2
def test_supplementary_generation_does_not_change_outstanding(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("1000.00"), WEEK_1_START)
    _record_delivery(farmer, grade, WEEK_1_START)
    first = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(first)
    farmer.refresh_from_db()
    after_finalise = farmer.outstanding_advance

    _record_delivery(farmer, grade, WEEK_1_END)
    supplementary = payouts.build_weekly_payout(farmer, WEEK_1_START)

    assert supplementary.pk != first.pk
    assert supplementary.status == PayoutStatus.DRAFT
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == after_finalise


@pytest.mark.django_db(transaction=True)
@pytest.mark.m2
def test_concurrent_generation_creates_one_draft_and_assigns_each_once():
    from concurrent.futures import ThreadPoolExecutor

    from django.db import connections

    from procurement.services import payouts

    farmer = Farmer.objects.create(name="Asha", phone="9000000001", village="Kolar")
    crop = Crop.objects.create(
        name="Maize", moisture_threshold=Decimal("14.00"), max_moisture=Decimal("20.00")
    )
    grade = CropGrade.objects.create(crop=crop, code="A")
    deliveries = [_model_delivery(farmer, grade, WEEK_1_START) for _ in range(8)]

    def build(_index):
        try:
            payouts.build_weekly_payout(Farmer.objects.get(pk=farmer.pk), WEEK_1_START)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(build, range(8)))

    assert Payout.objects.filter(farmer=farmer).count() == 1
    draft = Payout.objects.get(farmer=farmer)
    assert set(draft.deliveries.values_list("pk", flat=True)) == {
        d.pk for d in deliveries
    }


# --- Finalisation: recovery bounds ----------------------------------------


@pytest.mark.m2
def test_recovery_below_the_cap_recovers_the_whole_outstanding(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("100.00"), WEEK_1_START)
    _model_delivery(farmer, grade, WEEK_1_START)  # gross 2450.00, cap 735.00

    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(payout)
    payout.refresh_from_db()
    farmer.refresh_from_db()

    assert payout.advance_deduction == Decimal("100.00")
    assert farmer.outstanding_advance == Decimal("0.00")
    assert payout.net_amount == Decimal("2350.00")


@pytest.mark.m2
def test_recovery_equal_to_the_cap_recovers_exactly_the_cap(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("735.00"), WEEK_1_START)
    _model_delivery(farmer, grade, WEEK_1_START)  # gross 2450.00, cap 735.00

    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(payout)
    payout.refresh_from_db()
    farmer.refresh_from_db()

    assert payout.advance_deduction == Decimal("735.00")
    assert farmer.outstanding_advance == Decimal("0.00")


@pytest.mark.m2
def test_recovery_above_the_cap_is_capped_and_carries_the_remainder(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("1000.00"), WEEK_1_START)
    _model_delivery(farmer, grade, WEEK_1_START)  # gross 2450.00, cap 735.00

    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(payout)
    payout.refresh_from_db()
    farmer.refresh_from_db()

    assert payout.advance_deduction == Decimal("735.00")
    assert farmer.outstanding_advance == Decimal("265.00")


@pytest.mark.m2
@pytest.mark.parametrize(
    ("gross", "expected_recovery"),
    [
        ("0.04", "0.01"),  # 0.012 -> 0.01 (down)
        ("0.05", "0.02"),  # 0.015 -> 0.02 (exact half cent, HALF_UP)
        ("0.15", "0.05"),  # 0.045 -> 0.05
        ("0.34", "0.10"),  # 0.102 -> 0.10 (down)
        ("0.35", "0.11"),  # 0.105 -> 0.11 (exact half cent, HALF_UP)
        ("2450.00", "735.00"),
    ],
)
def test_recovery_rounding_boundaries(farmer, grade, gross, expected_recovery):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("1000.00"), WEEK_1_START)
    _model_delivery(farmer, grade, WEEK_1_START, amount=Decimal(gross))

    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(payout)
    payout.refresh_from_db()
    farmer.refresh_from_db()

    assert payout.gross_amount == Decimal(gross)
    assert payout.advance_deduction == Decimal(expected_recovery)
    assert payout.net_amount == payout.gross_amount - payout.advance_deduction
    assert farmer.outstanding_advance == Decimal("1000.00") - Decimal(expected_recovery)


@pytest.mark.m2
def test_large_advance_is_recovered_across_successive_weeks(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("2500.00"), WEEK_1_START)

    expected_deductions = [
        Decimal("735.00"),  # 30% of 2450.00
        Decimal("735.00"),
        Decimal("735.00"),
        Decimal("295.00"),  # cap 735.00, but only 295.00 outstanding remains
    ]
    for offset, expected in enumerate(expected_deductions):
        week_start = WEEK_1_START + timedelta(weeks=offset)
        _model_delivery(farmer, grade, week_start)
        payout = payouts.build_weekly_payout(farmer, week_start)
        payouts.finalise_payout(payout)
        payout.refresh_from_db()
        farmer.refresh_from_db()
        assert payout.advance_deduction == expected

    assert farmer.outstanding_advance == Decimal("0.00")
    assert advances.assert_outstanding_reconciles(farmer).is_reconciled


# --- Finalisation: repeated, concurrent, rollback --------------------------


@pytest.mark.m2
def test_repeated_finalisation_does_not_recover_or_touch_the_frozen_payout(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("500.00"), WEEK_1_START)
    _model_delivery(farmer, grade, WEEK_1_START)
    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(payout)
    payout.refresh_from_db()
    farmer.refresh_from_db()

    frozen = (
        payout.status,
        payout.gross_amount,
        payout.advance_deduction,
        payout.net_amount,
        payout.finalised_at,
        farmer.outstanding_advance,
    )

    with pytest.raises(payouts.PayoutStateError):
        payouts.finalise_payout(payout)

    payout.refresh_from_db()
    farmer.refresh_from_db()
    assert (
        payout.status,
        payout.gross_amount,
        payout.advance_deduction,
        payout.net_amount,
        payout.finalised_at,
        farmer.outstanding_advance,
    ) == frozen


@pytest.mark.django_db(transaction=True)
@pytest.mark.m2
def test_concurrent_finalisation_recovers_exactly_once():
    from concurrent.futures import ThreadPoolExecutor

    from django.db import connections

    from procurement.services import advances, payouts

    farmer = Farmer.objects.create(name="Asha", phone="9000000001", village="Kolar")
    advances.post_advance(Farmer.objects.get(pk=farmer.pk), Decimal("1000.00"), WEEK_1_START)
    crop = Crop.objects.create(
        name="Maize", moisture_threshold=Decimal("14.00"), max_moisture=Decimal("20.00")
    )
    grade = CropGrade.objects.create(crop=crop, code="A")
    _model_delivery(farmer, grade, WEEK_1_START)
    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)

    outcomes = []

    def finalise(_index):
        try:
            payouts.finalise_payout(Payout.objects.get(pk=payout.pk))
            outcomes.append("finalised")
        except payouts.PayoutStateError:
            outcomes.append("conflict")
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(finalise, range(2)))

    assert sorted(outcomes) == ["conflict", "finalised"]
    payout.refresh_from_db()
    farmer.refresh_from_db()
    assert payout.status == PayoutStatus.FINALISED
    assert payout.advance_deduction == Decimal("735.00")
    assert farmer.outstanding_advance == Decimal("265.00")


@pytest.mark.m2
def test_finalisation_rolls_back_every_write_on_failure(farmer, grade, monkeypatch):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("1000.00"), WEEK_1_START)
    _model_delivery(farmer, grade, WEEK_1_START)
    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)

    def explode(self, *args, **kwargs):
        raise RuntimeError("simulated failure after the payout write")

    monkeypatch.setattr(Farmer, "save", explode)

    with pytest.raises(RuntimeError):
        payouts.finalise_payout(payout)

    fresh = Payout.objects.get(pk=payout.pk)
    assert fresh.status == PayoutStatus.DRAFT
    assert fresh.finalised_at is None
    assert fresh.advance_deduction == Decimal("0.00")
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("1000.00")


# --- Settlement (mark paid) ------------------------------------------------


@pytest.mark.m2
def test_mark_paid_preserves_the_finalised_values_and_balance(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("400.00"), WEEK_1_START)
    _model_delivery(farmer, grade, WEEK_1_START)
    _model_delivery(farmer, grade, WEEK_1_END)
    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(payout)
    payout.refresh_from_db()
    farmer.refresh_from_db()

    gross = sum(d.amount for d in payout.deliveries.all())
    assert payout.gross_amount == gross
    assert payout.net_amount == payout.gross_amount - payout.advance_deduction

    frozen = (
        payout.gross_amount,
        payout.advance_deduction,
        payout.net_amount,
        payout.finalised_at,
        set(payout.deliveries.values_list("pk", flat=True)),
        farmer.outstanding_advance,
    )

    paid = payouts.mark_payout_paid(payout)
    paid.refresh_from_db()
    farmer.refresh_from_db()

    assert paid.status == PayoutStatus.PAID
    assert paid.paid_at is not None
    assert (
        paid.gross_amount,
        paid.advance_deduction,
        paid.net_amount,
        paid.finalised_at,
        set(paid.deliveries.values_list("pk", flat=True)),
        farmer.outstanding_advance,
    ) == frozen


@pytest.mark.m2
def test_mark_paid_requires_a_finalised_payout(farmer, grade):
    from procurement.services import payouts

    _model_delivery(farmer, grade, WEEK_1_START)
    draft = payouts.build_weekly_payout(farmer, WEEK_1_START)

    with pytest.raises(payouts.PayoutStateError):
        payouts.mark_payout_paid(draft)

    draft.refresh_from_db()
    assert draft.status == PayoutStatus.DRAFT
    assert draft.paid_at is None


@pytest.mark.m2
def test_mark_paid_twice_is_rejected_without_changing_paid_at(farmer, grade):
    from procurement.services import payouts

    _model_delivery(farmer, grade, WEEK_1_START)
    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(payout)
    paid = payouts.mark_payout_paid(payout)
    paid.refresh_from_db()

    with pytest.raises(payouts.PayoutStateError):
        payouts.mark_payout_paid(paid)

    paid.refresh_from_db()
    assert paid.status == PayoutStatus.PAID
    assert paid.paid_at is not None


@pytest.mark.m2
def test_refinalising_a_paid_payout_is_rejected(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("500.00"), WEEK_1_START)
    _model_delivery(farmer, grade, WEEK_1_START)
    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(payout)
    paid = payouts.mark_payout_paid(payout)
    farmer.refresh_from_db()
    outstanding = farmer.outstanding_advance

    with pytest.raises(payouts.PayoutStateError):
        payouts.finalise_payout(paid)

    farmer.refresh_from_db()
    assert farmer.outstanding_advance == outstanding


@pytest.mark.m2
def test_nonpositive_net_settlement_is_payable_without_extra_recovery(farmer, grade):
    from procurement.services import advances, payouts

    advances.post_advance(farmer, Decimal("500.00"), WEEK_1_START)
    # The original lives outside WEEK_1 so the week holds only the debit note.
    original = _model_delivery(farmer, grade, date(2026, 2, 9))
    Delivery.objects.create(
        farmer=farmer,
        kind=DeliveryKind.DEBIT_NOTE,
        original_delivery=original,
        correction_magnitude=Decimal("100.00"),
        reason="rate applied was too high",
        accounting_date=WEEK_1_START,
        amount=Decimal("-100.00"),
    )

    payout = payouts.build_weekly_payout(farmer, WEEK_1_START)
    payouts.finalise_payout(payout)
    payout.refresh_from_db()
    farmer.refresh_from_db()

    assert payout.gross_amount == Decimal("-100.00")
    assert payout.advance_deduction == Decimal("0.00")
    assert payout.net_amount == Decimal("-100.00")
    outstanding = farmer.outstanding_advance

    paid = payouts.mark_payout_paid(payout)
    paid.refresh_from_db()
    farmer.refresh_from_db()

    assert paid.status == PayoutStatus.PAID
    assert paid.net_amount == Decimal("-100.00")
    assert farmer.outstanding_advance == outstanding
