"""M3: payout generation, finalisation and settlement endpoints."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.m3

WEEK = "2026-01-05"
PAYLOAD = {
    "delivered_on": WEEK,
    "gross_weight_kg": "100.000",
    "moisture_percent": "14.00",
}


def _error(response):
    return response.json()["error"]


def _record_delivery(api_client, farmer, grade):
    api_client.post(
        reverse("api:delivery-list"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    )


def _generate(api_client, farmer, week=WEEK):
    return api_client.post(
        reverse("api:payout-generate"),
        {"farmer": farmer.id, "week_start": week},
        format="json",
    )


@pytest.mark.django_db
def test_generate_builds_draft(api_client, farmer, grade, price):
    _record_delivery(api_client, farmer, grade)
    response = _generate(api_client, farmer)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "DRAFT"
    assert body["week_start"] == WEEK
    assert body["week_end"] == "2026-01-11"
    assert body["gross_amount"] == "2450.00"


@pytest.mark.django_db
def test_generate_empty_week_is_conflict(api_client, farmer):
    response = _generate(api_client, farmer)
    assert response.status_code == 409
    assert _error(response)["code"] == "empty_week"


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
def test_finalise_recovers_advance_once(api_client, farmer, grade, price):
    api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "500.00", "given_on": WEEK},
        format="json",
    )
    _record_delivery(api_client, farmer, grade)
    payout_id = _generate(api_client, farmer).json()["id"]

    response = api_client.post(reverse("api:payout-finalise", args=[payout_id]))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FINALISED"
    assert body["advance_deduction"] == "500.00"
    assert body["net_amount"] == "1950.00"
    farmer.refresh_from_db()
    assert str(farmer.outstanding_advance) == "0.00"


@pytest.mark.django_db
def test_finalise_twice_is_conflict(api_client, farmer, grade, price):
    _record_delivery(api_client, farmer, grade)
    payout_id = _generate(api_client, farmer).json()["id"]
    api_client.post(reverse("api:payout-finalise", args=[payout_id]))

    again = api_client.post(reverse("api:payout-finalise", args=[payout_id]))
    assert again.status_code == 409
    assert _error(again)["code"] == "payout_state_error"


@pytest.mark.django_db
def test_generate_settled_week_with_nothing_new_is_conflict(
    api_client, farmer, grade, price
):
    _record_delivery(api_client, farmer, grade)
    payout_id = _generate(api_client, farmer).json()["id"]
    api_client.post(reverse("api:payout-finalise", args=[payout_id]))

    again = _generate(api_client, farmer)
    assert again.status_code == 409
    assert _error(again)["code"] == "payout_state_error"


@pytest.mark.django_db
def test_finalise_missing_payout_is_not_found(api_client):
    response = api_client.post(reverse("api:payout-finalise", args=[9999]))
    assert response.status_code == 404
    assert _error(response)["code"] == "not_found"


@pytest.mark.django_db
def test_pay_settles_finalised_payout(api_client, farmer, grade, price):
    _record_delivery(api_client, farmer, grade)
    payout_id = _generate(api_client, farmer).json()["id"]
    api_client.post(reverse("api:payout-finalise", args=[payout_id]))

    response = api_client.post(reverse("api:payout-pay", args=[payout_id]))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PAID"
    assert body["net_amount"] == "2450.00"
    assert body["paid_at"] is not None


@pytest.mark.django_db
def test_pay_draft_is_conflict(api_client, farmer, grade, price):
    _record_delivery(api_client, farmer, grade)
    payout_id = _generate(api_client, farmer).json()["id"]

    response = api_client.post(reverse("api:payout-pay", args=[payout_id]))
    assert response.status_code == 409
    assert _error(response)["code"] == "payout_state_error"


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
def test_payout_detail(api_client, farmer, grade, price):
    _record_delivery(api_client, farmer, grade)
    payout_id = _generate(api_client, farmer).json()["id"]
    response = api_client.get(reverse("api:payout-detail", args=[payout_id]))
    assert response.status_code == 200
    assert response.json()["id"] == payout_id
