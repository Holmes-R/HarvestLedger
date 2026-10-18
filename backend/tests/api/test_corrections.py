"""M3: credit/debit note correction endpoints."""

from datetime import date

import pytest
from django.urls import reverse

from procurement.services import payouts

pytestmark = pytest.mark.m3

PAYLOAD = {
    "delivered_on": "2026-01-05",
    "gross_weight_kg": "100.000",
    "moisture_percent": "14.00",
}


def _error(response):
    return response.json()["error"]


def _settled_delivery(api_client, farmer, grade, price):
    created = api_client.post(
        reverse("api:delivery-list"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    ).json()
    payout = payouts.build_weekly_payout(farmer, date(2026, 1, 5))
    payouts.finalise_payout(payout)
    return created


@pytest.mark.django_db
def test_credit_note_has_positive_amount(api_client, farmer, grade, price):
    delivery = _settled_delivery(api_client, farmer, grade, price)
    response = api_client.post(
        reverse("api:correction-list"),
        {
            "original_delivery": delivery["id"],
            "kind": "CREDIT_NOTE",
            "magnitude": "50.00",
            "reason": "Quality bonus",
        },
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "CREDIT_NOTE"
    assert body["amount"] == "50.00"
    assert body["correction_magnitude"] == "50.00"
    assert body["original_delivery"] == delivery["id"]


@pytest.mark.django_db
def test_debit_note_has_negative_amount(api_client, farmer, grade, price):
    delivery = _settled_delivery(api_client, farmer, grade, price)
    response = api_client.post(
        reverse("api:correction-list"),
        {
            "original_delivery": delivery["id"],
            "kind": "DEBIT_NOTE",
            "magnitude": "50.00",
            "reason": "Overpayment",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["amount"] == "-50.00"


@pytest.mark.django_db
def test_correction_against_unsettled_delivery_is_rejected(
    api_client, farmer, grade, price
):
    created = api_client.post(
        reverse("api:delivery-list"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    ).json()
    response = api_client.post(
        reverse("api:correction-list"),
        {
            "original_delivery": created["id"],
            "kind": "CREDIT_NOTE",
            "magnitude": "50.00",
            "reason": "Premature",
        },
        format="json",
    )
    assert response.status_code == 409
    assert _error(response)["code"] == "original_not_settled"


@pytest.mark.django_db
def test_correction_missing_original_is_not_found(api_client, farmer):
    response = api_client.post(
        reverse("api:correction-list"),
        {
            "original_delivery": 9999,
            "kind": "CREDIT_NOTE",
            "magnitude": "50.00",
            "reason": "Ghost",
        },
        format="json",
    )
    assert response.status_code == 404
    assert _error(response)["code"] == "original_not_found"


@pytest.mark.django_db
def test_correction_missing_reason_is_rejected(api_client, farmer, grade, price):
    delivery = _settled_delivery(api_client, farmer, grade, price)
    response = api_client.post(
        reverse("api:correction-list"),
        {
            "original_delivery": delivery["id"],
            "kind": "CREDIT_NOTE",
            "magnitude": "50.00",
            "reason": "",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "reason" in _error(response)["details"]


@pytest.mark.django_db
def test_correction_list_and_detail(api_client, farmer, grade, price):
    delivery = _settled_delivery(api_client, farmer, grade, price)
    created = api_client.post(
        reverse("api:correction-list"),
        {
            "original_delivery": delivery["id"],
            "kind": "CREDIT_NOTE",
            "magnitude": "50.00",
            "reason": "Bonus",
        },
        format="json",
    ).json()

    listing = api_client.get(reverse("api:correction-list"), {"farmer": farmer.id})
    assert listing.status_code == 200
    assert listing.json()["count"] == 1

    ok = api_client.get(reverse("api:correction-detail", args=[created["id"]]))
    assert ok.status_code == 200

    # An ordinary procurement delivery is not addressable as a correction.
    missing = api_client.get(reverse("api:correction-detail", args=[delivery["id"]]))
    assert missing.status_code == 404
    assert _error(missing)["code"] == "not_found"
