"""M3: farmer/crop/price-list reference-data endpoints.

Covers the approved contract for the five catalog endpoints: valid create and
update, missing fields, unknown references, duplicate prices, the strict write
contract (protected / unsupported fields) and historical preservation.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from procurement.models import Crop, CropGrade, Delivery, Farmer, PriceListEntry

pytestmark = pytest.mark.m3

DAY = "2026-01-05"
DELIVERY = {
    "delivered_on": DAY,
    "gross_weight_kg": "100.000",
    "moisture_percent": "14.00",
}


def _error(response):
    return response.json()["error"]


def _codes(body):
    return [grade["code"] for grade in body["allowed_grades"]]


# --- Farmers ----------------------------------------------------------------


@pytest.mark.django_db
def test_farmer_patch_updates_editable_fields(api_client, farmer):
    response = api_client.patch(
        reverse("api:farmer-detail", args=[farmer.id]),
        {"village": "Mandya", "bank_reference": "XXXX1234"},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["village"] == "Mandya"
    assert body["bank_reference"] == "XXXX1234"
    assert body["outstanding_advance"] == "0.00"
    farmer.refresh_from_db()
    assert farmer.village == "Mandya"


@pytest.mark.django_db
def test_farmer_patch_cannot_write_outstanding_advance(api_client, farmer):
    response = api_client.patch(
        reverse("api:farmer-detail", args=[farmer.id]),
        {"outstanding_advance": "500.00"},
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "protected_field"
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("0.00")


@pytest.mark.django_db
def test_farmer_patch_rejects_invalid_phone(api_client, farmer):
    response = api_client.patch(
        reverse("api:farmer-detail", args=[farmer.id]),
        {"phone": "12345"},
        format="json",
    )
    assert response.status_code == 400
    assert "phone" in _error(response)["details"]


@pytest.mark.django_db
def test_farmer_patch_rejects_unknown_field(api_client, farmer):
    response = api_client.patch(
        reverse("api:farmer-detail", args=[farmer.id]),
        {"nickname": "Ashu"},
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "unsupported_field"


@pytest.mark.django_db
def test_farmer_patch_unknown_farmer_is_not_found(api_client, db):
    response = api_client.patch(
        reverse("api:farmer-detail", args=[9999]),
        {"village": "Nowhere"},
        format="json",
    )
    assert response.status_code == 404
    assert _error(response)["code"] == "farmer_not_found"


@pytest.mark.django_db
def test_farmer_create_missing_name(api_client, db):
    response = api_client.post(
        reverse("api:farmer-list"),
        {"phone": "9000000009", "village": "Kolar"},
        format="json",
    )
    assert response.status_code == 400
    assert "name" in _error(response)["details"]


# --- Crops ------------------------------------------------------------------


@pytest.mark.django_db
def test_crop_create_returns_allowed_grades(api_client, db):
    response = api_client.post(
        reverse("api:crop-list"),
        {
            "name": "Ragi",
            "moisture_threshold": "12.00",
            "max_moisture": "18.00",
            "allowed_grades": ["A", "B", "A"],
        },
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert _codes(body) == ["A", "B"]  # de-duplicated, ordered
    crop = Crop.objects.get(pk=body["id"])
    assert set(crop.grades.values_list("code", flat=True)) == {"A", "B"}


@pytest.mark.django_db
def test_crop_create_missing_name(api_client, db):
    response = api_client.post(
        reverse("api:crop-list"),
        {"moisture_threshold": "12.00", "max_moisture": "18.00"},
        format="json",
    )
    assert response.status_code == 400
    assert "name" in _error(response)["details"]


@pytest.mark.django_db
def test_crop_create_invalid_moisture_is_unprocessable(api_client, db):
    response = api_client.post(
        reverse("api:crop-list"),
        {"name": "Ragi", "moisture_threshold": "25.00", "max_moisture": "10.00"},
        format="json",
    )
    assert response.status_code == 422
    assert _error(response)["code"] == "invalid_moisture_bounds"
    assert Crop.objects.count() == 0


@pytest.mark.django_db
def test_crop_create_duplicate_name_is_conflict(api_client, crop):
    response = api_client.post(
        reverse("api:crop-list"),
        {"name": "Maize", "moisture_threshold": "14.00", "max_moisture": "20.00"},
        format="json",
    )
    assert response.status_code == 409
    assert _error(response)["code"] == "duplicate_crop"


@pytest.mark.django_db
def test_crop_create_rejects_overlong_grade_code(api_client, db):
    response = api_client.post(
        reverse("api:crop-list"),
        {
            "name": "Ragi",
            "moisture_threshold": "12.00",
            "max_moisture": "18.00",
            "allowed_grades": ["ABC"],
        },
        format="json",
    )
    assert response.status_code == 400
    assert "allowed_grades" in _error(response)["details"]


@pytest.mark.django_db
def test_crop_detail_exposes_grades_and_hidden_computed_fields(api_client, crop, grade):
    response = api_client.get(reverse("api:crop-detail", args=[crop.id]))
    assert response.status_code == 200
    body = response.json()
    assert body["allowed_grades"] == [{"id": grade.id, "code": "A"}]
    assert body["moisture_threshold"] == "14.00"
    assert "outstanding_advance" not in body


@pytest.mark.django_db
def test_crop_patch_preserves_existing_delivery_snapshot(
    api_client, farmer, grade, price
):
    recorded = api_client.post(
        reverse("api:delivery-list"),
        {**DELIVERY, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    )
    assert recorded.status_code == 201
    snapshot_id = recorded.json()["id"]

    patched = api_client.patch(
        reverse("api:crop-detail", args=[grade.crop_id]),
        {"moisture_threshold": "10.00"},
        format="json",
    )
    assert patched.status_code == 200
    assert patched.json()["moisture_threshold"] == "10.00"

    snapshot = Delivery.objects.get(pk=snapshot_id)
    assert snapshot.threshold_used == Decimal("14.00")
    assert snapshot.amount == Decimal("2450.00")


@pytest.mark.django_db
def test_crop_patch_adds_grade(api_client, crop, grade):
    response = api_client.patch(
        reverse("api:crop-detail", args=[crop.id]),
        {"allowed_grades": ["A", "B"]},
        format="json",
    )
    assert response.status_code == 200
    assert _codes(response.json()) == ["A", "B"]
    assert CropGrade.objects.filter(crop=crop, code="B").exists()


@pytest.mark.django_db
def test_crop_patch_removes_unused_grade(api_client, crop, grade):
    CropGrade.objects.create(crop=crop, code="B")
    response = api_client.patch(
        reverse("api:crop-detail", args=[crop.id]),
        {"allowed_grades": ["A"]},
        format="json",
    )
    assert response.status_code == 200
    assert _codes(response.json()) == ["A"]
    assert not CropGrade.objects.filter(crop=crop, code="B").exists()


@pytest.mark.django_db
def test_crop_patch_used_grade_conflict_rolls_back(api_client, crop, grade, price):
    # Grade A is priced -> historical. Removing it is refused, and the new
    # grade "B" added in the same request must not be persisted.
    response = api_client.patch(
        reverse("api:crop-detail", args=[crop.id]),
        {"allowed_grades": ["B"]},
        format="json",
    )
    assert response.status_code == 409
    assert _error(response)["code"] == "grade_in_use"
    assert CropGrade.objects.filter(crop=crop, code="A").exists()
    assert not CropGrade.objects.filter(crop=crop, code="B").exists()


@pytest.mark.django_db
def test_crop_patch_protected_field_rejected(api_client, crop):
    response = api_client.patch(
        reverse("api:crop-detail", args=[crop.id]),
        {"grades": [{"id": 1, "code": "A"}]},
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "protected_field"


@pytest.mark.django_db
def test_crop_patch_unknown_crop_is_not_found(api_client, db):
    response = api_client.patch(
        reverse("api:crop-detail", args=[9999]),
        {"max_moisture": "20.00"},
        format="json",
    )
    assert response.status_code == 404
    assert _error(response)["code"] == "crop_not_found"


# --- Price lists (append-only) ----------------------------------------------


@pytest.mark.django_db
def test_price_list_path_and_first_entry(api_client):
    assert reverse("api:price-list") == "/api/v1/price-lists/"


@pytest.mark.django_db
def test_price_list_create_appends_entry(api_client, crop, grade):
    response = api_client.post(
        reverse("api:price-list"),
        {
            "crop": crop.id,
            "grade": "A",
            "price_per_kg": "31.00",
            "effective_from": "2026-03-01",
        },
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["price_per_kg"] == "31.00"
    assert body["crop_grade_code"] == "A"
    assert body["crop"] == crop.id


@pytest.mark.django_db
def test_price_list_duplicate_is_conflict(api_client, crop, grade, price):
    response = api_client.post(
        reverse("api:price-list"),
        {
            "crop": crop.id,
            "grade": "A",
            "price_per_kg": "31.00",
            "effective_from": price.effective_from,
        },
        format="json",
    )
    assert response.status_code == 409
    assert _error(response)["code"] == "price_already_exists"
    assert PriceListEntry.objects.filter(crop_grade=grade).count() == 1


@pytest.mark.django_db
def test_price_list_unknown_crop_is_not_found(api_client, grade):
    response = api_client.post(
        reverse("api:price-list"),
        {
            "crop": 9999,
            "grade": "A",
            "price_per_kg": "31.00",
            "effective_from": "2026-03-01",
        },
        format="json",
    )
    assert response.status_code == 404
    assert _error(response)["code"] == "crop_not_found"


@pytest.mark.django_db
def test_price_list_disallowed_grade_is_unprocessable(api_client, crop, grade):
    response = api_client.post(
        reverse("api:price-list"),
        {
            "crop": crop.id,
            "grade": "Z",
            "price_per_kg": "31.00",
            "effective_from": "2026-03-01",
        },
        format="json",
    )
    assert response.status_code == 422
    assert _error(response)["code"] == "grade_not_allowed"


@pytest.mark.django_db
def test_price_list_rejects_computed_field(api_client, crop, grade):
    response = api_client.post(
        reverse("api:price-list"),
        {
            "crop": crop.id,
            "grade": "A",
            "crop_grade": grade.id,
            "price_per_kg": "31.00",
            "effective_from": "2026-03-01",
        },
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "protected_field"


@pytest.mark.django_db
def test_price_list_is_append_only(api_client, price):
    update = api_client.patch(
        reverse("api:price-list"),
        {"price_per_kg": "99.00"},
        format="json",
    )
    assert update.status_code == 405
    delete = api_client.delete(reverse("api:price-list"))
    assert delete.status_code == 405
    detail = api_client.get(
        f"{reverse('api:price-list')}{price.id}/"
    )
    assert detail.status_code == 404
    price.refresh_from_db()
    assert price.price_per_kg == Decimal("24.50")
    assert date(2026, 1, 1) == price.effective_from


@pytest.mark.django_db
def test_farmer_crud_has_no_delete(api_client, farmer):
    response = api_client.delete(reverse("api:farmer-detail", args=[farmer.id]))
    assert response.status_code == 405
    assert Farmer.objects.filter(pk=farmer.id).exists()
