"""M3: request/response serializer conventions and protected-field rejection."""

import pytest
from django.urls import reverse

from procurement.models import Advance, Delivery, Farmer, PriceListEntry

pytestmark = pytest.mark.m3

DAY = "2026-01-05"
DELIVERY = {
    "delivered_on": DAY,
    "gross_weight_kg": "100.000",
    "moisture_percent": "14.00",
}


def _error(response):
    return response.json()["error"]


# --- Protected computed fields are rejected, not silently ignored -----------


@pytest.mark.django_db
def test_delivery_write_rejects_computed_fields(api_client, farmer, grade, price):
    response = api_client.post(
        reverse("api:delivery-list"),
        {
            **DELIVERY,
            "farmer": farmer.id,
            "crop_grade": grade.id,
            "amount": "999999.00",
            "net_kg": "1.00000",
        },
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "protected_field"
    assert Delivery.objects.count() == 0


@pytest.mark.django_db
def test_farmer_write_rejects_computed_balance(api_client):
    response = api_client.post(
        reverse("api:farmer-list"),
        {
            "name": "Asha",
            "phone": "9000000001",
            "village": "Kolar",
            "outstanding_advance": "500.00",
        },
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "protected_field"
    assert Farmer.objects.count() == 0


@pytest.mark.django_db
def test_advance_write_rejects_server_fields(api_client, farmer):
    response = api_client.post(
        reverse("api:advance-list"),
        {
            "farmer": farmer.id,
            "amount": "500.00",
            "given_on": DAY,
            "created_at": "2026-01-05T00:00:00Z",
        },
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "protected_field"
    assert Advance.objects.count() == 0


@pytest.mark.django_db
def test_payout_write_rejects_computed_totals(api_client, farmer):
    response = api_client.post(
        reverse("api:payout-generate"),
        {"farmer": farmer.id, "week_start": DAY, "net_amount": "1.00"},
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "protected_field"


@pytest.mark.django_db
def test_price_write_rejects_output_only_fields(api_client, crop, grade):
    response = api_client.post(
        reverse("api:price-list"),
        {
            "crop": crop.id,
            "grade": "A",
            "price_per_kg": "30.00",
            "effective_from": "2026-02-01",
            "crop_grade": grade.id,
        },
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "protected_field"
    assert PriceListEntry.objects.count() == 0


@pytest.mark.django_db
def test_unsupported_field_is_rejected(api_client, farmer):
    response = api_client.post(
        reverse("api:farmer-list"),
        {"name": "Asha", "phone": "9000000001", "village": "Kolar", "nonsense": 1},
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "unsupported_field"


# --- Missing / null / blank -------------------------------------------------


@pytest.mark.django_db
def test_missing_required_field(api_client, farmer, grade, price):
    response = api_client.post(
        reverse("api:delivery-list"),
        {
            "farmer": farmer.id,
            "crop_grade": grade.id,
            "delivered_on": DAY,
            "gross_weight_kg": "100.000",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "moisture_percent" in _error(response)["fields"]


@pytest.mark.django_db
def test_null_on_non_nullable_field(api_client, farmer, grade, price):
    response = api_client.post(
        reverse("api:delivery-list"),
        {**DELIVERY, "farmer": farmer.id, "crop_grade": grade.id, "delivered_on": None},
        format="json",
    )
    assert response.status_code == 400
    assert "delivered_on" in _error(response)["fields"]


@pytest.mark.django_db
def test_blank_required_char_field(api_client):
    response = api_client.post(
        reverse("api:farmer-list"),
        {"name": "", "phone": "9000000001", "village": "Kolar"},
        format="json",
    )
    assert response.status_code == 400
    assert "name" in _error(response)["fields"]


# --- ISO dates and decimal precision ----------------------------------------


@pytest.mark.django_db
def test_non_iso_date_is_rejected(api_client, farmer, grade, price):
    response = api_client.post(
        reverse("api:delivery-list"),
        {**DELIVERY, "farmer": farmer.id, "crop_grade": grade.id,
         "delivered_on": "05/01/2026"},
        format="json",
    )
    assert response.status_code == 400
    assert "delivered_on" in _error(response)["fields"]


@pytest.mark.django_db
def test_over_precise_weight_is_rejected_before_service(api_client, farmer, grade, price):
    response = api_client.post(
        reverse("api:delivery-list"),
        {**DELIVERY, "farmer": farmer.id, "crop_grade": grade.id,
         "gross_weight_kg": "100.0001"},
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "max_decimal_places"


# --- Input/output separation and decimal strings ----------------------------


@pytest.mark.django_db
def test_price_input_and_output_shapes_differ(api_client, crop, grade):
    response = api_client.post(
        reverse("api:price-list"),
        {
            "crop": crop.id,
            "grade": "A",
            "price_per_kg": "30.00",
            "effective_from": "2026-02-01",
        },
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    # Input used ``grade``; output exposes the resolved grade as ``crop_grade``.
    assert body["crop_grade"] == grade.id
    assert body["crop_grade_code"] == "A"
    assert isinstance(body["price_per_kg"], str)
    assert body["price_per_kg"] == "30.00"
