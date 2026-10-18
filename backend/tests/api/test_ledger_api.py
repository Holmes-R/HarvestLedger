"""M3: farmer ledger endpoint."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from procurement.clock import FrozenClock, use_clock
from procurement.models import Delivery, DeliveryKind
from procurement.services import advances, corrections, delivery, payouts

pytestmark = pytest.mark.m3

WEEK = date(2026, 1, 5)  # Monday
WEEK2 = date(2026, 2, 9)  # Monday
CLOCK = FrozenClock(datetime(2026, 2, 1, 6, tzinfo=UTC))


def _seed(api_client, farmer, grade, price):
    advances.post_advance(farmer, Decimal("500.00"), WEEK)
    with use_clock(CLOCK):
        delivery.record_delivery(
            farmer=farmer,
            crop_grade=grade,
            delivered_on=WEEK,
            gross_weight_kg=Decimal("100.000"),
            moisture_percent=Decimal("14.00"),
        )
    payout = payouts.build_weekly_payout(farmer, WEEK)
    payouts.finalise_payout(payout)


def _seed_two_weeks(farmer, grade):
    """Jan: advance 500 + delivery, finalised. Feb: advance 200 + delivery, DRAFT."""
    advances.post_advance(farmer, Decimal("500.00"), WEEK)
    with use_clock(FrozenClock(datetime(2026, 1, 6, 6, tzinfo=UTC))):
        delivery.record_delivery(
            farmer=farmer,
            crop_grade=grade,
            delivered_on=WEEK,
            gross_weight_kg=Decimal("100.000"),
            moisture_percent=Decimal("14.00"),
        )
    payouts.finalise_payout(payouts.build_weekly_payout(farmer, WEEK))

    advances.post_advance(farmer, Decimal("200.00"), date(2026, 2, 10))
    with use_clock(FrozenClock(datetime(2026, 2, 10, 6, tzinfo=UTC))):
        delivery.record_delivery(
            farmer=farmer,
            crop_grade=grade,
            delivered_on=WEEK2,
            gross_weight_kg=Decimal("100.000"),
            moisture_percent=Decimal("14.00"),
        )
    payouts.build_weekly_payout(farmer, WEEK2)  # left as DRAFT


@pytest.mark.django_db
def test_ledger_projects_balances_reconciliation_and_money_strings(
    api_client, farmer, grade, price
):
    _seed(api_client, farmer, grade, price)

    response = api_client.get(reverse("api:farmer-ledger", args=[farmer.id]))
    assert response.status_code == 200
    body = response.json()

    assert body["farmer_id"] == farmer.id
    assert body["outstanding_advance"] == "0.00"  # 500 advance fully recovered
    assert body["total_advances"] == "500.00"
    assert body["total_recovered"] == "500.00"
    assert body["settled_earnings"] == "2450.00"
    assert body["reconciliation"]["is_reconciled"] is True
    assert body["earnings_identity_holds"] is True

    assert len(body["deliveries"]) == 1
    assert body["deliveries"][0]["amount"] == "2450.00"
    assert len(body["advances"]) == 1
    assert len(body["payouts"]) == 1
    assert body["payouts"][0]["status"] == "FINALISED"
    assert body["payouts"][0]["advance_deduction"] == "500.00"

    # Money and quantities are decimal strings, never JSON numbers.
    for value in (body["outstanding_advance"], body["settled_earnings"]):
        assert isinstance(value, str)


@pytest.mark.django_db
def test_ledger_missing_farmer_is_not_found(api_client):
    response = api_client.get(reverse("api:farmer-ledger", args=[9999]))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "farmer_not_found"


@pytest.mark.django_db
def test_ledger_totals_reconcile_without_double_counting(api_client, farmer, grade, price):
    _seed_two_weeks(farmer, grade)

    body = api_client.get(reverse("api:farmer-ledger", args=[farmer.id])).json()

    assert body["total_advances"] == "700.00"
    assert body["total_recovered"] == "500.00"  # only the FINALISED payout
    assert body["settled_earnings"] == "2450.00"
    assert body["draft_projection"] == "2450.00"  # DRAFT is a projection, not earnings
    assert body["unassigned_earnings"] == "0.00"
    assert body["total_recorded_amount"] == "4900.00"
    assert body["earnings_identity_holds"] is True
    assert body["outstanding_advance"] == "200.00"
    assert body["reconciliation"]["expected_outstanding"] == "200.00"
    assert body["reconciliation"]["stored_outstanding"] == "200.00"
    assert body["reconciliation"]["is_reconciled"] is True

    assert {p["status"] for p in body["payouts"]} == {"FINALISED", "DRAFT"}
    draft = next(p for p in body["payouts"] if p["status"] == "DRAFT")
    settled = next(p for p in body["payouts"] if p["status"] == "FINALISED")
    assert draft["advance_deduction"] == "0.00"
    assert settled["advance_deduction"] == "500.00"


@pytest.mark.django_db
def test_ledger_separates_deliveries_advances_and_payouts(api_client, farmer, grade, price):
    _seed_two_weeks(farmer, grade)
    body = api_client.get(reverse("api:farmer-ledger", args=[farmer.id])).json()

    assert len(body["advances"]) == 2
    assert sorted(a["amount"] for a in body["advances"]) == ["200.00", "500.00"]
    assert len(body["deliveries"]) == 2
    assert {d["kind"] for d in body["deliveries"]} == {"PROCUREMENT"}
    assert all(d["is_correction"] is False for d in body["deliveries"])
    assert len(body["payouts"]) == 2
    assert isinstance(body["outstanding_advance"], str)


@pytest.mark.django_db
def test_ledger_distinguishes_corrections(api_client, farmer, grade, price):
    _seed_two_weeks(farmer, grade)
    original = Delivery.objects.get(farmer=farmer, accounting_date=WEEK)
    corrections.record_correction(
        original,
        DeliveryKind.CREDIT_NOTE,
        Decimal("50.00"),
        "quality allowance",
        clock=FrozenClock(datetime(2026, 2, 15, 6, tzinfo=UTC)),
    )

    body = api_client.get(reverse("api:farmer-ledger", args=[farmer.id])).json()

    notes = [d for d in body["deliveries"] if d["is_correction"]]
    assert len(notes) == 1
    assert notes[0]["kind"] == "CREDIT_NOTE"
    assert notes[0]["amount"] == "50.00"  # credit is positive, linked to its original
    assert notes[0]["original_delivery"] == original.id
    assert notes[0]["payout"] is None  # recorded after settlement, still unassigned
    assert body["unassigned_earnings"] == "50.00"
    assert body["total_recorded_amount"] == "4950.00"
    assert body["earnings_identity_holds"] is True


@pytest.mark.django_db
def test_ledger_bounded_history_keeps_full_totals(api_client, farmer, grade, price):
    _seed_two_weeks(farmer, grade)

    full = api_client.get(reverse("api:farmer-ledger", args=[farmer.id])).json()
    assert len(full["advances"]) == 2
    assert len(full["deliveries"]) == 2
    assert len(full["payouts"]) == 2
    assert full["history_from"] is None
    assert full["history_to"] is None

    bounded = api_client.get(
        reverse("api:farmer-ledger", args=[farmer.id]),
        {"from": "2026-02-01", "to": "2026-02-28"},
    ).json()
    assert bounded["history_from"] == "2026-02-01"
    assert bounded["history_to"] == "2026-02-28"
    assert len(bounded["advances"]) == 1
    assert bounded["advances"][0]["amount"] == "200.00"
    assert len(bounded["deliveries"]) == 1
    assert len(bounded["payouts"]) == 1
    assert bounded["payouts"][0]["status"] == "DRAFT"

    # Bounding the history never changes the account totals or balance.
    assert bounded["total_advances"] == full["total_advances"] == "700.00"
    assert bounded["settled_earnings"] == full["settled_earnings"] == "2450.00"
    assert bounded["outstanding_advance"] == full["outstanding_advance"] == "200.00"
    assert bounded["earnings_identity_holds"] is True
    assert bounded["reconciliation"]["is_reconciled"] is True


@pytest.mark.django_db
def test_ledger_rejects_invalid_bounds(api_client, farmer):
    url = reverse("api:farmer-ledger", args=[farmer.id])
    bad_date = api_client.get(url, {"from": "not-a-date"})
    assert bad_date.status_code == 400
    assert bad_date.json()["error"]["code"] == "invalid"

    inverted = api_client.get(url, {"from": "2026-03-01", "to": "2026-01-01"})
    assert inverted.status_code == 400
    assert inverted.json()["error"]["code"] == "invalid"
