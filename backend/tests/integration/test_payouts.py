"""Payout grouping, advance recovery and finalisation rules.

Model-level behaviour (one Draft per farmer/week, single delivery membership) is
enforced at M1 and passes. The remaining cases exercise the M2 service layer
(marker ``m2``) and are expected to fail until it exists; they are not skipped.

Contract exercised (to be provided by M2)
-----------------------------------------
``procurement.services.payouts.build_weekly_payout(farmer, week_start) ->
Payout | None`` -- creates/extends the DRAFT payout for the Monday-Sunday week,
attaching that farmer's unassigned deliveries in ``[week_start, week_start+6]``;
returns ``None`` when the week has no eligible deliveries.

``procurement.services.payouts.finalise_payout(payout) -> Payout`` -- sets
FINALISED, computes ``advance_deduction = min(outstanding_advance, 30% of
gross_amount)``, reduces the farmer's balance once, and freezes the payout.
``PayoutStateError`` is raised for illegal transitions (re-finalising a payout,
re-building a finalised week).

``procurement.services.advances.post_advance(farmer, amount, given_on)`` --
increases the farmer's outstanding balance.

``procurement.services.delivery.record_delivery(...)`` -- freezes a delivery.
"""

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

WEEK_1_START = date(2026, 1, 5)  # Monday
WEEK_1_END = date(2026, 1, 11)  # Sunday
WEEK_2_START = date(2026, 1, 12)


@pytest.fixture
def farmer(db):
    return Farmer.objects.create(name="Asha", phone="0000000001", village="Kolar")


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


def _model_delivery(farmer, grade, accounting_date, price=Decimal("24.50")):
    return Delivery.objects.create(
        farmer=farmer,
        kind=DeliveryKind.PROCUREMENT,
        crop_grade=grade,
        delivered_on=accounting_date,
        accounting_date=accounting_date,
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
        applied_price=price,
        amount=Decimal("2450.00"),
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


# --- M2 rule tests (expected to fail until M2) -----------------------------


@pytest.mark.m2
def test_monday_to_sunday_selection(farmer, grade):
    from procurement.services import payouts

    inside_mon = _record_delivery(farmer, grade, WEEK_1_START)
    inside_sun = _record_delivery(farmer, grade, WEEK_1_END)
    before = _record_delivery(farmer, grade, date(2026, 1, 4))
    after = _record_delivery(farmer, grade, WEEK_2_START)
    other_farmer = Farmer.objects.create(
        name="Bina", phone="0000000002", village="Kolar"
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
