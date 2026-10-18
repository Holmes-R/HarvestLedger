"""M3: farmer ledger endpoint."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from procurement.clock import FrozenClock, use_clock
from procurement.services import advances, delivery, payouts

pytestmark = pytest.mark.m3

WEEK = date(2026, 1, 5)  # Monday
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
