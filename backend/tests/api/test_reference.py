"""M3: health, reference data and prices endpoints."""

from decimal import Decimal

import pytest
from django.urls import reverse

from procurement.models import Farmer

pytestmark = pytest.mark.m3


def _error(response):
    return response.json()["error"]


@pytest.mark.django_db
def test_health(api_client):
    response = api_client.get(reverse("api:health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_farmer_create_returns_decimal_string_balance(api_client):
    response = api_client.post(
        reverse("api:farmer-list"),
        {"name": "Asha", "phone": "9000000001", "village": "Kolar"},
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["outstanding_advance"] == "0.00"
    assert isinstance(body["outstanding_advance"], str)
    assert Farmer.objects.filter(pk=body["id"]).exists()


@pytest.mark.django_db
def test_farmer_create_rejects_invalid_phone_with_field_error(api_client):
    response = api_client.post(
        reverse("api:farmer-list"),
        {"name": "Asha", "phone": "12345", "village": "Kolar"},
        format="json",
    )
    assert response.status_code == 400
    assert "phone" in _error(response)["fields"]
    assert not Farmer.objects.exists()


@pytest.mark.django_db
def test_farmer_list_search(api_client, farmer, other_farmer):
    response = api_client.get(reverse("api:farmer-list"), {"search": "Tumkur"})
    assert response.status_code == 200
    ids = [row["id"] for row in response.json()["results"]]
    assert ids == [other_farmer.id]


@pytest.mark.django_db
def test_farmer_detail_and_not_found(api_client, farmer):
    ok = api_client.get(reverse("api:farmer-detail", args=[farmer.id]))
    assert ok.status_code == 200
    assert ok.json()["phone"] == "9000000001"

    missing = api_client.get(reverse("api:farmer-detail", args=[9999]))
    assert missing.status_code == 404
    assert _error(missing)["code"] == "farmer_not_found"


@pytest.mark.django_db
def test_crops_and_crop_detail(api_client, crop):
    listing = api_client.get(reverse("api:crop-list"))
    assert listing.status_code == 200
    assert listing.json()["results"][0]["moisture_threshold"] == "14.00"

    detail = api_client.get(reverse("api:crop-detail", args=[crop.id]))
    assert detail.status_code == 200

    missing = api_client.get(reverse("api:crop-detail", args=[9999]))
    assert missing.status_code == 404
    assert _error(missing)["code"] == "crop_not_found"


@pytest.mark.django_db
def test_grades_filter_by_crop(api_client, grade, other_farmer):
    from procurement.models import Crop

    other_crop = Crop.objects.create(
        name="Ragi", moisture_threshold=Decimal("12.00"), max_moisture=Decimal("18.00")
    )
    filtered = api_client.get(reverse("api:grade-list"), {"crop": other_crop.id})
    assert filtered.status_code == 200
    assert filtered.json()["results"] == []

    missing = api_client.get(reverse("api:grade-list"), {"crop": 9999})
    assert missing.status_code == 404
    assert _error(missing)["code"] == "crop_not_found"

    invalid = api_client.get(reverse("api:grade-list"), {"crop": "abc"})
    assert invalid.status_code == 400


@pytest.mark.django_db
def test_price_create_by_code_and_list(api_client, crop, grade):
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
    assert body["price_per_kg"] == "30.00"
    assert body["crop_grade_code"] == "A"

    listing = api_client.get(reverse("api:price-list"), {"crop_grade": grade.id})
    assert listing.status_code == 200
    assert listing.json()["count"] == 1


@pytest.mark.django_db
def test_price_create_duplicate_is_conflict(api_client, crop, grade, price):
    response = api_client.post(
        reverse("api:price-list"),
        {
            "crop": crop.id,
            "grade": "A",
            "price_per_kg": "30.00",
            "effective_from": "2026-01-01",
        },
        format="json",
    )
    assert response.status_code == 409
    assert _error(response)["code"] == "price_already_exists"


@pytest.mark.django_db
def test_price_create_disallowed_grade_is_unprocessable(api_client, crop, price):
    response = api_client.post(
        reverse("api:price-list"),
        {
            "crop": crop.id,
            "grade": "Z",
            "price_per_kg": "30.00",
            "effective_from": "2026-02-01",
        },
        format="json",
    )
    assert response.status_code == 422
    assert _error(response)["code"] == "grade_not_allowed"


@pytest.mark.django_db
def test_price_create_missing_crop_is_not_found(api_client, grade):
    response = api_client.post(
        reverse("api:price-list"),
        {
            "crop": 9999,
            "grade": "A",
            "price_per_kg": "30.00",
            "effective_from": "2026-02-01",
        },
        format="json",
    )
    assert response.status_code == 404
    assert _error(response)["code"] == "crop_not_found"


@pytest.mark.django_db
def test_price_create_rejects_over_precise_rate(api_client, crop, grade):
    response = api_client.post(
        reverse("api:price-list"),
        {
            "crop": crop.id,
            "grade": "A",
            "price_per_kg": "30.001",
            "effective_from": "2026-02-01",
        },
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "max_decimal_places"
