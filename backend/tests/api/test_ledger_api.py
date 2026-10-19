"""M3: farmer ledger endpoint (paginated event timeline + account summary)."""

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


def _error(response):
    return response.json()["error"]


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


def _events(body):
    return body["results"]


@pytest.mark.django_db
def test_ledger_returns_page_envelope_with_summary(api_client, farmer, grade, price):
    _seed(api_client, farmer, grade, price)

    response = api_client.get(reverse("api:farmer-ledger", args=[farmer.id]))
    assert response.status_code == 200
    body = response.json()

    assert set(body) == {"count", "next", "previous", "summary", "results"}
    assert body["count"] == 3  # one delivery, one advance, one payout
    assert body["next"] is None and body["previous"] is None

    summary = body["summary"]
    assert summary["farmer_id"] == farmer.id
    assert summary["outstanding_advance"] == "0.00"  # 500 advance fully recovered
    assert summary["total_advances"] == "500.00"
    assert summary["total_recovered"] == "500.00"
    assert summary["settled_earnings"] == "2450.00"
    assert summary["reconciliation"]["is_reconciled"] is True
    assert summary["earnings_identity_holds"] is True

    # Money and quantities are decimal strings, never JSON numbers.
    assert isinstance(summary["outstanding_advance"], str)
    assert isinstance(summary["settled_earnings"], str)
    for event in _events(body):
        assert isinstance(event["amount"], str)
        assert event["event_type"] in {"DELIVERY", "CORRECTION", "ADVANCE", "PAYOUT"}


@pytest.mark.django_db
def test_ledger_missing_farmer_is_not_found(api_client):
    response = api_client.get(reverse("api:farmer-ledger", args=[9999]))
    assert response.status_code == 404
    assert _error(response)["code"] == "farmer_not_found"


@pytest.mark.django_db
def test_ledger_totals_reconcile_without_double_counting(
    api_client, farmer, grade, price
):
    _seed_two_weeks(farmer, grade)

    body = api_client.get(reverse("api:farmer-ledger", args=[farmer.id])).json()
    summary = body["summary"]

    assert summary["total_advances"] == "700.00"
    assert summary["total_recovered"] == "500.00"  # only the FINALISED payout
    assert summary["settled_earnings"] == "2450.00"
    assert summary["draft_projection"] == "2450.00"  # DRAFT is a projection
    assert summary["unassigned_earnings"] == "0.00"
    assert summary["total_recorded_amount"] == "4900.00"
    assert summary["earnings_identity_holds"] is True
    assert summary["outstanding_advance"] == "200.00"
    assert summary["reconciliation"]["expected_outstanding"] == "200.00"
    assert summary["reconciliation"]["stored_outstanding"] == "200.00"
    assert summary["reconciliation"]["is_reconciled"] is True

    payouts_ = [e for e in _events(body) if e["event_type"] == "PAYOUT"]
    assert {p["payout"]["status"] for p in payouts_} == {"FINALISED", "DRAFT"}
    draft = next(p for p in payouts_ if p["payout"]["status"] == "DRAFT")
    settled = next(p for p in payouts_ if p["payout"]["status"] == "FINALISED")
    assert draft["payout"]["advance_deduction"] == "0.00"
    assert settled["payout"]["advance_deduction"] == "500.00"


@pytest.mark.django_db
def test_ledger_separates_event_types(api_client, farmer, grade, price):
    _seed_two_weeks(farmer, grade)
    body = api_client.get(reverse("api:farmer-ledger", args=[farmer.id])).json()

    events = _events(body)
    by_type = {}
    for event in events:
        by_type.setdefault(event["event_type"], []).append(event)

    assert len(by_type["ADVANCE"]) == 2
    assert [e["amount"] for e in by_type["ADVANCE"]] == ["200.00", "500.00"]
    assert len(by_type["DELIVERY"]) == 2
    assert all(e["delivery"]["kind"] == "PROCUREMENT" for e in by_type["DELIVERY"])
    assert all(
        e["advance"] is None and e["payout"] is None for e in by_type["DELIVERY"]
    )
    assert len(by_type["PAYOUT"]) == 2
    assert isinstance(body["summary"]["outstanding_advance"], str)


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

    notes = [e for e in _events(body) if e["event_type"] == "CORRECTION"]
    assert len(notes) == 1
    note = notes[0]
    assert note["delivery"]["kind"] == "CREDIT_NOTE"
    assert note["delivery"]["is_correction"] is True
    assert note["delivery"]["amount"] == "50.00"
    assert note["delivery"]["original_delivery"] == original.id
    assert note["delivery"]["payout"] is None  # recorded after settlement
    assert note["advance"] is None and note["payout"] is None
    assert body["summary"]["unassigned_earnings"] == "50.00"
    assert body["summary"]["earnings_identity_holds"] is True


@pytest.mark.django_db
def test_ledger_event_type_filter_and_validation(api_client, farmer, grade, price):
    _seed_two_weeks(farmer, grade)
    url = reverse("api:farmer-ledger", args=[farmer.id])

    only_payouts = api_client.get(url, {"event_type": "PAYOUT"}).json()
    assert only_payouts["count"] == 2
    assert {e["event_type"] for e in only_payouts["results"]} == {"PAYOUT"}

    only_deliveries = api_client.get(url, {"event_type": "DELIVERY"}).json()
    assert only_deliveries["count"] == 2
    assert all(e["payout"] is None for e in only_deliveries["results"])

    bad = api_client.get(url, {"event_type": "RECOVERY"})
    assert bad.status_code == 400
    assert _error(bad)["code"] == "invalid"
    assert "event_type" in _error(bad)["details"]


@pytest.mark.django_db
def test_ledger_bounded_history_keeps_full_totals(api_client, farmer, grade, price):
    _seed_two_weeks(farmer, grade)
    url = reverse("api:farmer-ledger", args=[farmer.id])

    full = api_client.get(url).json()
    assert full["count"] == 6  # 2 deliveries + 2 advances + 2 payouts
    assert full["summary"]["history_from"] is None
    assert full["summary"]["history_to"] is None

    bounded = api_client.get(url, {"from": "2026-02-01", "to": "2026-02-28"}).json()
    assert bounded["summary"]["history_from"] == "2026-02-01"
    assert bounded["summary"]["history_to"] == "2026-02-28"
    # Feb window: one advance, one delivery, one payout.
    assert bounded["count"] == 3
    types = sorted(e["event_type"] for e in bounded["results"])
    assert types == ["ADVANCE", "DELIVERY", "PAYOUT"]

    # Bounding the history never changes the account totals or balance.
    for key in ("total_advances", "settled_earnings", "outstanding_advance"):
        assert bounded["summary"][key] == full["summary"][key]
    assert bounded["summary"]["earnings_identity_holds"] is True


@pytest.mark.django_db
def test_ledger_rejects_invalid_bounds(api_client, farmer):
    url = reverse("api:farmer-ledger", args=[farmer.id])
    bad_date = api_client.get(url, {"from": "not-a-date"})
    assert bad_date.status_code == 400
    assert _error(bad_date)["code"] == "invalid"

    inverted = api_client.get(url, {"from": "2026-03-01", "to": "2026-01-01"})
    assert inverted.status_code == 400
    assert _error(inverted)["code"] == "invalid"


@pytest.mark.django_db
def test_ledger_is_paginated_with_default_page_size(api_client, farmer):
    advances.post_advance(farmer, Decimal("10.00"), WEEK)  # a valid anchor
    for _ in range(25):
        advances.post_advance(farmer, Decimal("1.00"), WEEK)

    url = reverse("api:farmer-ledger", args=[farmer.id])
    first = api_client.get(url).json()
    assert first["count"] == 26
    assert len(first["results"]) == 20  # default page size, bounded
    assert first["next"] is not None

    second = api_client.get(url, {"page": 2}).json()
    assert len(second["results"]) == 6
    assert second["previous"] is not None

    # A requested page size is clamped to the 100-event maximum.
    capped = api_client.get(url, {"page_size": 1000}).json()
    assert len(capped["results"]) == 26
