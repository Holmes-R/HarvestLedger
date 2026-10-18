"""M3: delivery preview, record, list, detail and edit endpoints."""

from datetime import date

import pytest
from django.urls import reverse

from procurement.models import Delivery
from procurement.services import payouts

pytestmark = pytest.mark.m3

DAY = "2026-01-05"  # Monday, price effective 2026-01-01
PAYLOAD = {
    "delivered_on": DAY,
    "gross_weight_kg": "100.000",
    "moisture_percent": "14.00",
}


def _error(response):
    return response.json()["error"]


@pytest.mark.django_db
def test_preview_returns_breakdown_without_writing(api_client, farmer, grade, price):
    response = api_client.post(
        reverse("api:delivery-preview"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["farmer_id"] == farmer.id
    assert body["applied_price"] == "24.50"
    assert body["deduction_percent"] == "0.00"
    assert body["net_kg"] == "100.00000"
    assert body["amount"] == "2450.00"
    assert isinstance(body["amount"], str)
    assert Delivery.objects.count() == 0


@pytest.mark.django_db
def test_preview_missing_price_is_unprocessable(api_client, farmer, grade):
    response = api_client.post(
        reverse("api:delivery-preview"),
        {
            **PAYLOAD,
            "farmer": farmer.id,
            "crop_grade": grade.id,
        },
        format="json",
    )
    assert response.status_code == 422
    assert _error(response)["code"] == "price_not_found"


@pytest.mark.django_db
def test_record_delivery_persists_snapshot(api_client, farmer, grade, price):
    response = api_client.post(
        reverse("api:delivery-list"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "PROCUREMENT"
    assert body["accounting_date"] == DAY
    assert body["amount"] == "2450.00"
    assert Delivery.objects.filter(pk=body["id"]).exists()


@pytest.mark.django_db
def test_record_future_delivery_is_rejected(api_client, farmer, grade, price):
    response = api_client.post(
        reverse("api:delivery-list"),
        {
            "farmer": farmer.id,
            "crop_grade": grade.id,
            "delivered_on": "2099-01-01",
            "gross_weight_kg": "100.000",
            "moisture_percent": "14.00",
        },
        format="json",
    )
    assert response.status_code == 422
    assert _error(response)["code"] == "future_delivery_date"


@pytest.mark.django_db
def test_record_moisture_above_maximum_is_unprocessable(
    api_client, farmer, grade, price
):
    response = api_client.post(
        reverse("api:delivery-list"),
        {
            **PAYLOAD,
            "farmer": farmer.id,
            "crop_grade": grade.id,
            "moisture_percent": "25.00",
        },
        format="json",
    )
    assert response.status_code == 422
    assert _error(response)["code"] == "moisture_exceeds_maximum"


@pytest.mark.django_db
def test_record_over_precise_weight_is_rejected(api_client, farmer, grade, price):
    response = api_client.post(
        reverse("api:delivery-list"),
        {
            **PAYLOAD,
            "farmer": farmer.id,
            "crop_grade": grade.id,
            "gross_weight_kg": "100.0001",
        },
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "max_decimal_places"


@pytest.mark.django_db
def test_list_filters_by_farmer_and_kind(
    api_client, farmer, other_farmer, grade, price
):
    for who in (farmer, other_farmer):
        api_client.post(
            reverse("api:delivery-list"),
            {**PAYLOAD, "farmer": who.id, "crop_grade": grade.id},
            format="json",
        )

    filtered = api_client.get(reverse("api:delivery-list"), {"farmer": farmer.id})
    assert filtered.status_code == 200
    assert filtered.json()["count"] == 1

    by_kind = api_client.get(reverse("api:delivery-list"), {"kind": "PROCUREMENT"})
    assert by_kind.json()["count"] == 2

    bad_kind = api_client.get(reverse("api:delivery-list"), {"kind": "NOPE"})
    assert bad_kind.status_code == 400

    bad_date = api_client.get(reverse("api:delivery-list"), {"from": "not-a-date"})
    assert bad_date.status_code == 400


@pytest.mark.django_db
def test_detail_and_not_found(api_client, farmer, grade, price):
    created = api_client.post(
        reverse("api:delivery-list"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    ).json()

    ok = api_client.get(reverse("api:delivery-detail", args=[created["id"]]))
    assert ok.status_code == 200
    assert ok.json()["id"] == created["id"]

    missing = api_client.get(reverse("api:delivery-detail", args=[9999]))
    assert missing.status_code == 404
    assert _error(missing)["code"] == "not_found"


@pytest.mark.django_db
def test_edit_recalculates_amount(api_client, farmer, grade, price):
    created = api_client.post(
        reverse("api:delivery-list"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    ).json()

    edited = api_client.patch(
        reverse("api:delivery-detail", args=[created["id"]]),
        {"gross_weight_kg": "50.000"},
        format="json",
    )
    assert edited.status_code == 200
    assert edited.json()["gross_weight_kg"] == "50.000"
    assert edited.json()["amount"] == "1225.00"


@pytest.mark.django_db
def test_edit_settled_delivery_is_conflict(api_client, farmer, grade, price):
    created = api_client.post(
        reverse("api:delivery-list"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    ).json()
    payout = payouts.build_weekly_payout(farmer, date(2026, 1, 5))
    payouts.finalise_payout(payout)

    response = api_client.patch(
        reverse("api:delivery-detail", args=[created["id"]]),
        {"gross_weight_kg": "50.000"},
        format="json",
    )
    assert response.status_code == 409
    assert _error(response)["code"] == "payout_state_error"
