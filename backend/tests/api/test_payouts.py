"""M3: payout generation, finalisation and settlement endpoints.

``POST /payouts/generate/`` returns a stable envelope: ``{"payout": <statement or
null>, "reason": <string or null>}``. An empty week is a successful no-op
(``200``), never an invented payout; a created/extended DRAFT is ``201``. Every
statement embeds its frozen member snapshots so the totals can be checked against
the rows that produced them.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

import pytest
from django.db import connections
from django.urls import reverse
from rest_framework.test import APIClient

from procurement.models import Delivery, Farmer, Payout, PriceListEntry

pytestmark = pytest.mark.m3

WEEK = "2026-01-05"
PAYLOAD = {
    "delivered_on": WEEK,
    "gross_weight_kg": "100.000",
    "moisture_percent": "14.00",
}


def _error(response):
    return response.json()["error"]


def _record_delivery(api_client, farmer, grade, **overrides):
    return api_client.post(
        reverse("api:delivery-list"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id, **overrides},
        format="json",
    )


def _generate(api_client, farmer, week=WEEK):
    return api_client.post(
        reverse("api:payout-generate"),
        {"farmer": farmer.id, "week_start": week},
        format="json",
    )


def _payout_id(api_client, farmer, week=WEEK):
    return _generate(api_client, farmer, week).json()["payout"]["id"]


# --- Generation -------------------------------------------------------------


@pytest.mark.django_db
def test_generate_builds_draft_statement(api_client, farmer, grade, price):
    _record_delivery(api_client, farmer, grade)
    response = _generate(api_client, farmer)
    assert response.status_code == 201
    body = response.json()
    assert body["reason"] is None
    statement = body["payout"]
    assert statement["status"] == "DRAFT"
    assert statement["farmer"] == farmer.id
    assert statement["farmer_name"] == "Asha"
    assert statement["week_start"] == WEEK
    assert statement["week_end"] == "2026-01-11"
    assert statement["gross_amount"] == "2450.00"
    assert [member["kind"] for member in statement["deliveries"]] == ["PROCUREMENT"]
    assert statement["deliveries"][0]["amount"] == "2450.00"


@pytest.mark.django_db
def test_generate_empty_week_returns_no_payout(api_client, farmer):
    response = _generate(api_client, farmer)
    assert response.status_code == 200
    body = response.json()
    assert body["payout"] is None
    assert body["reason"] == "NO_ELIGIBLE_DELIVERIES"
    assert Payout.objects.count() == 0


@pytest.mark.django_db
def test_generate_missing_farmer_is_not_found(api_client):
    response = api_client.post(
        reverse("api:payout-generate"),
        {"farmer": 9999, "week_start": WEEK},
        format="json",
    )
    assert response.status_code == 404
    assert _error(response)["code"] == "farmer_not_found"


@pytest.mark.django_db
def test_repeated_generation_reuses_draft_and_refreshes_membership(
    api_client, farmer, grade, price
):
    _record_delivery(api_client, farmer, grade)
    first = _generate(api_client, farmer)
    assert first.status_code == 201
    first_id = first.json()["payout"]["id"]
    assert len(first.json()["payout"]["deliveries"]) == 1

    _record_delivery(api_client, farmer, grade)
    again = _generate(api_client, farmer)
    statement = again.json()["payout"]
    assert again.status_code == 201
    assert statement["id"] == first_id  # same DRAFT, not a second payout
    assert len(statement["deliveries"]) == 2
    assert statement["gross_amount"] == "4900.00"
    assert statement["net_amount"] == "4900.00"  # a draft never recovers
    assert Payout.objects.filter(farmer=farmer).count() == 1


@pytest.mark.django_db
def test_supplementary_payout_after_finalisation(api_client, farmer, grade, price):
    _record_delivery(api_client, farmer, grade)
    first_id = _payout_id(api_client, farmer)
    api_client.post(reverse("api:payout-finalise", args=[first_id]))

    _record_delivery(api_client, farmer, grade)  # late record for the same week
    response = _generate(api_client, farmer)
    assert response.status_code == 201
    statement = response.json()["payout"]
    assert statement["id"] != first_id
    assert statement["week_start"] == WEEK
    assert statement["gross_amount"] == "2450.00"  # only the new delivery
    assert Payout.objects.filter(farmer=farmer).count() == 2


@pytest.mark.django_db
def test_generate_settled_week_with_nothing_new_is_conflict(
    api_client, farmer, grade, price
):
    _record_delivery(api_client, farmer, grade)
    payout_id = _payout_id(api_client, farmer)
    api_client.post(reverse("api:payout-finalise", args=[payout_id]))

    again = _generate(api_client, farmer)
    assert again.status_code == 409
    assert _error(again)["code"] == "payout_state_error"


@pytest.mark.django_db
def test_generate_refuses_client_supplied_membership_and_status(
    api_client, farmer, grade, price
):
    for forbidden in ("deliveries", "status", "farmer_name", "net_amount"):
        response = api_client.post(
            reverse("api:payout-generate"),
            {"farmer": farmer.id, "week_start": WEEK, forbidden: "x"},
            format="json",
        )
        assert response.status_code == 400, forbidden
        assert _error(response)["code"] == "protected_field", forbidden
    assert Payout.objects.count() == 0


# --- Finalisation and settlement --------------------------------------------


@pytest.mark.django_db
def test_finalise_recovers_advance_once(api_client, farmer, grade, price):
    api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "500.00", "given_on": WEEK},
        format="json",
    )
    _record_delivery(api_client, farmer, grade)
    payout_id = _payout_id(api_client, farmer)

    response = api_client.post(reverse("api:payout-finalise", args=[payout_id]))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FINALISED"
    assert body["advance_deduction"] == "500.00"
    assert body["net_amount"] == "1950.00"
    assert body["finalised_at"] is not None
    assert len(body["deliveries"]) == 1  # the frozen member is in the statement
    farmer.refresh_from_db()
    assert str(farmer.outstanding_advance) == "0.00"


@pytest.mark.django_db
def test_recovery_is_capped_at_thirty_percent_rounded_to_the_cent(
    api_client, farmer, grade
):
    # grade A at 1.00/kg so 100.050 net kg yields exactly 100.05 gross; 30% is
    # 30.015, which must round down to 30.01 (never up to a cent the farmer owes).
    PriceListEntry.objects.create(
        crop_grade=grade,
        price_per_kg=Decimal("1.00"),
        effective_from=date(2026, 1, 1),
    )
    api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "500.00", "given_on": WEEK},
        format="json",
    )
    _record_delivery(api_client, farmer, grade, gross_weight_kg="100.050")
    payout_id = _payout_id(api_client, farmer)

    body = api_client.post(reverse("api:payout-finalise", args=[payout_id])).json()
    assert body["gross_amount"] == "100.05"
    assert body["advance_deduction"] == "30.01"
    assert body["net_amount"] == "70.04"
    farmer.refresh_from_db()
    assert str(farmer.outstanding_advance) == "469.99"


@pytest.mark.django_db
def test_finalise_twice_is_conflict(api_client, farmer, grade, price):
    _record_delivery(api_client, farmer, grade)
    payout_id = _payout_id(api_client, farmer)
    api_client.post(reverse("api:payout-finalise", args=[payout_id]))

    again = api_client.post(reverse("api:payout-finalise", args=[payout_id]))
    assert again.status_code == 409
    assert _error(again)["code"] == "payout_state_error"


@pytest.mark.django_db
def test_finalise_missing_payout_is_not_found(api_client):
    response = api_client.post(reverse("api:payout-finalise", args=[9999]))
    assert response.status_code == 404
    assert _error(response)["code"] == "not_found"


@pytest.mark.django_db
def test_mark_paid_settles_finalised_payout(api_client, farmer, grade, price):
    _record_delivery(api_client, farmer, grade)
    payout_id = _payout_id(api_client, farmer)
    api_client.post(reverse("api:payout-finalise", args=[payout_id]))

    response = api_client.post(reverse("api:payout-mark-paid", args=[payout_id]))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PAID"
    assert body["net_amount"] == "2450.00"
    assert body["paid_at"] is not None


@pytest.mark.django_db
def test_mark_paid_before_finalisation_is_conflict(api_client, farmer, grade, price):
    _record_delivery(api_client, farmer, grade)
    payout_id = _payout_id(api_client, farmer)

    response = api_client.post(reverse("api:payout-mark-paid", args=[payout_id]))
    assert response.status_code == 409
    assert _error(response)["code"] == "payout_state_error"


@pytest.mark.django_db
def test_repeated_and_out_of_order_transitions_are_conflicts(
    api_client, farmer, grade, price
):
    _record_delivery(api_client, farmer, grade)
    payout_id = _payout_id(api_client, farmer)
    api_client.post(reverse("api:payout-finalise", args=[payout_id]))
    api_client.post(reverse("api:payout-mark-paid", args=[payout_id]))

    for endpoint in ("api:payout-finalise", "api:payout-mark-paid"):
        response = api_client.post(reverse(endpoint, args=[payout_id]))
        assert response.status_code == 409, endpoint
        assert _error(response)["code"] == "payout_state_error", endpoint


@pytest.mark.django_db
def test_finalised_payout_is_financially_immutable(api_client, farmer, grade, price):
    api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "500.00", "given_on": WEEK},
        format="json",
    )
    _record_delivery(api_client, farmer, grade)
    payout_id = _payout_id(api_client, farmer)
    finalised = api_client.post(reverse("api:payout-finalise", args=[payout_id])).json()
    farmer.refresh_from_db()
    balance = str(farmer.outstanding_advance)

    paid = api_client.post(reverse("api:payout-mark-paid", args=[payout_id])).json()
    for field in ("gross_amount", "advance_deduction", "net_amount"):
        assert paid[field] == finalised[field], field
    assert paid["net_amount"] == "1950.00"
    farmer.refresh_from_db()
    assert str(farmer.outstanding_advance) == balance  # never recovered twice

    # There is no generic mutation route: a payout is changed only by the two
    # explicit transitions above.
    assert (
        api_client.patch(
            reverse("api:payout-detail", args=[payout_id]), {}, format="json"
        ).status_code
        == 405
    )
    assert (
        api_client.delete(reverse("api:payout-detail", args=[payout_id])).status_code
        == 405
    )
    assert (
        api_client.post(reverse("api:payout-list"), {}, format="json").status_code
        == 405
    )


@pytest.mark.django_db
def test_finalisation_rolls_back_on_unexpected_failure(
    api_client, farmer, grade, price, monkeypatch
):
    api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "500.00", "given_on": WEEK},
        format="json",
    )
    _record_delivery(api_client, farmer, grade)
    payout_id = _payout_id(api_client, farmer)

    # The payout row is written before the farmer balance is persisted; a failure
    # there must roll the whole finalisation back, leaving the DRAFT untouched.
    def boom(self, *args, **kwargs):
        raise RuntimeError("failure after the payout write")

    monkeypatch.setattr(Farmer, "save", boom)
    response = api_client.post(reverse("api:payout-finalise", args=[payout_id]))
    assert response.status_code == 500
    assert _error(response)["code"] == "internal_error"

    payout = Payout.objects.get(pk=payout_id)
    assert payout.status == "DRAFT"
    assert payout.advance_deduction == Decimal("0.00")
    assert payout.finalised_at is None
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("500.00")


# --- Listing and detail -----------------------------------------------------


@pytest.mark.django_db
def test_payout_list_filters(api_client, farmer, grade, price):
    _record_delivery(api_client, farmer, grade)
    _generate(api_client, farmer)

    by_farmer = api_client.get(reverse("api:payout-list"), {"farmer": farmer.id})
    assert by_farmer.status_code == 200
    assert by_farmer.json()["count"] == 1

    by_status = api_client.get(reverse("api:payout-list"), {"status": "DRAFT"})
    assert by_status.json()["count"] == 1

    bad_status = api_client.get(reverse("api:payout-list"), {"status": "NOPE"})
    assert bad_status.status_code == 400


@pytest.mark.django_db
def test_payout_detail_includes_members(api_client, farmer, grade, price):
    _record_delivery(api_client, farmer, grade)
    payout_id = _payout_id(api_client, farmer)
    response = api_client.get(reverse("api:payout-detail", args=[payout_id]))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == payout_id
    assert len(body["deliveries"]) == 1
    assert body["deliveries"][0]["id"] == Delivery.objects.get().pk


# --- Concurrency (real PostgreSQL, independent connections) -----------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_generation_via_api_creates_one_draft(farmer, grade, price):
    seed = APIClient()
    for _ in range(5):
        assert _record_delivery(seed, farmer, grade).status_code == 201

    def generate(_index):
        try:
            client = APIClient()
            response = _generate(client, farmer)
            return response.status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(generate, range(4)))

    assert set(codes) == {201}
    assert Payout.objects.filter(farmer=farmer).count() == 1
    assert Payout.objects.get(farmer=farmer).deliveries.count() == 5


@pytest.mark.django_db(transaction=True)
def test_concurrent_finalisation_via_api_recovers_once(farmer, grade, price):
    seed = APIClient()
    seed.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "2000.00", "given_on": WEEK},
        format="json",
    )
    _record_delivery(seed, farmer, grade)
    payout_id = _payout_id(seed, farmer)

    def finalise(_index):
        try:
            client = APIClient()
            response = client.post(reverse("api:payout-finalise", args=[payout_id]))
            return response.status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(finalise, range(2)))

    assert sorted(codes) == [200, 409]  # one winner, one controlled conflict
    payout = Payout.objects.get(pk=payout_id)
    assert payout.status == "FINALISED"
    assert payout.advance_deduction == Decimal("735.00")  # 30% cap, applied once
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("1265.00")  # 2000 - 735
