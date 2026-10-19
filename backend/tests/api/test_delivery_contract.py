"""M3: delivery preview/save/edit and nested correction contract."""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from procurement.models import Crop, CropGrade, Delivery, Payout, PriceListEntry
from procurement.services import payouts

pytestmark = pytest.mark.m3

DAY = "2026-01-05"  # Monday; price fixture effective 2026-01-01 @ 24.50
BASE = {
    "delivered_on": DAY,
    "gross_weight_kg": "100.000",
    "moisture_percent": "14.00",
}


def _error(response):
    return response.json()["error"]


def _record(api_client, farmer, grade, **overrides):
    return api_client.post(
        reverse("api:delivery-list"),
        {**BASE, "farmer": farmer.id, "crop_grade": grade.id, **overrides},
        format="json",
    )


def _settled(api_client, farmer, grade):
    created = _record(api_client, farmer, grade).json()
    payouts.finalise_payout(payouts.build_weekly_payout(farmer, date(2026, 1, 5)))
    return created


# --- Preview ----------------------------------------------------------------


@pytest.mark.django_db
def test_preview_returns_full_breakdown_and_writes_nothing(
    api_client, farmer, grade, price
):
    response = api_client.post(
        reverse("api:delivery-preview"),
        {
            **BASE,
            "farmer": farmer.id,
            "crop_grade": grade.id,
            "moisture_percent": "18.00",
        },
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["farmer_id"] == farmer.id
    assert body["crop_grade"] == grade.id
    assert body["delivered_on"] == DAY
    assert body["accounting_date"] == DAY  # effective business date
    assert body["threshold_used"] == "14.00"
    assert body["price_list_entry"] == price.id  # identifies the applied entry
    assert body["applied_price"] == "24.50"  # and its rate
    assert body["deduction_percent"] == "4.00"
    assert body["deduction_kg"] == "4.00000"
    assert body["net_kg"] == "96.00000"
    assert body["amount"] == "2352.00"
    for value in ("applied_price", "net_kg", "amount"):
        assert isinstance(body[value], str)
    assert Delivery.objects.count() == 0  # persist nothing


@pytest.mark.django_db
def test_preview_malformed_input(api_client, farmer, grade, price):
    response = api_client.post(
        reverse("api:delivery-preview"),
        {**BASE, "farmer": farmer.id, "crop_grade": grade.id, "gross_weight_kg": "abc"},
        format="json",
    )
    assert response.status_code == 400
    assert "gross_weight_kg" in _error(response)["details"]


@pytest.mark.django_db
def test_preview_unknown_references(api_client, farmer, grade, price):
    missing_grade = api_client.post(
        reverse("api:delivery-preview"),
        {**BASE, "farmer": farmer.id, "crop_grade": 9999},
        format="json",
    )
    assert missing_grade.status_code == 404
    assert _error(missing_grade)["code"] == "crop_grade_not_found"

    missing_farmer = api_client.post(
        reverse("api:delivery-preview"),
        {**BASE, "farmer": 9999, "crop_grade": grade.id},
        format="json",
    )
    assert missing_farmer.status_code == 404
    assert _error(missing_farmer)["code"] == "farmer_not_found"


@pytest.mark.django_db
def test_preview_missing_price_is_unprocessable(api_client, farmer):
    crop = Crop.objects.create(
        name="Ragi",
        moisture_threshold=Decimal("12.00"),
        max_moisture=Decimal("18.00"),
    )
    grade = CropGrade.objects.create(crop=crop, code="A")
    response = api_client.post(
        reverse("api:delivery-preview"),
        {**BASE, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    )
    assert response.status_code == 422
    assert _error(response)["code"] == "price_not_found"


@pytest.mark.django_db
def test_preview_moisture_boundaries(api_client, farmer, grade, price):
    def preview(moisture):
        return api_client.post(
            reverse("api:delivery-preview"),
            {
                **BASE,
                "farmer": farmer.id,
                "crop_grade": grade.id,
                "moisture_percent": moisture,
            },
            format="json",
        )

    at_threshold = preview("14.00").json()
    assert at_threshold["deduction_percent"] == "0.00"
    assert at_threshold["amount"] == "2450.00"

    below_threshold = preview("13.99").json()
    assert below_threshold["deduction_percent"] == "0.00"
    assert below_threshold["amount"] == "2450.00"

    at_max = preview("20.00").json()
    assert at_max["deduction_percent"] == "6.00"
    assert at_max["net_kg"] == "94.00000"
    assert at_max["amount"] == "2303.00"

    above_max = preview("20.01")
    assert above_max.status_code == 422
    assert _error(above_max)["code"] == "moisture_exceeds_maximum"


# --- Save -------------------------------------------------------------------


@pytest.mark.django_db
def test_save_recalculates_authoritatively_when_price_changes(
    api_client, farmer, grade, price
):
    previewed = api_client.post(
        reverse("api:delivery-preview"),
        {**BASE, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    ).json()
    assert previewed["applied_price"] == "24.50"

    # A new, later-effective price supersedes the one the preview saw.
    PriceListEntry.objects.create(
        crop_grade=grade,
        price_per_kg=Decimal("30.00"),
        effective_from=date(2026, 1, 5),
    )
    saved = _record(api_client, farmer, grade)
    assert saved.status_code == 201
    body = saved.json()
    assert body["applied_price"] == "30.00"  # recalculated, preview not trusted
    assert body["amount"] == "3000.00"
    stored = Delivery.objects.get(pk=body["id"])
    assert stored.applied_price == Decimal("30.00")
    assert stored.amount == Decimal("3000.00")


@pytest.mark.django_db
def test_save_rejects_forged_breakdown_and_membership(api_client, farmer, grade, price):
    response = _record(
        api_client,
        farmer,
        grade,
        amount="999999.00",
        deduction_kg="1.00000",
        applied_price="1.00",
        net_kg="1.00000",
        price_list_entry=price.id,
        payout=1,
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "protected_field"
    assert Delivery.objects.count() == 0


@pytest.mark.django_db
def test_save_capacity_overflow_is_rejected(api_client, farmer, grade, price):
    response = _record(api_client, farmer, grade, gross_weight_kg="9999999999.000")
    assert response.status_code == 400
    assert "gross_weight_kg" in _error(response)["details"]
    assert Delivery.objects.count() == 0


# --- Editing ----------------------------------------------------------------


@pytest.mark.django_db
def test_edit_refreshes_draft_totals(api_client, farmer, grade, price):
    created = _record(api_client, farmer, grade).json()
    draft = payouts.build_weekly_payout(farmer, date(2026, 1, 5))
    assert draft.gross_amount == Decimal("2450.00")

    edited = api_client.patch(
        reverse("api:delivery-detail", args=[created["id"]]),
        {"gross_weight_kg": "50.000"},
        format="json",
    )
    assert edited.status_code == 200
    assert edited.json()["amount"] == "1225.00"

    draft.refresh_from_db()
    assert draft.gross_amount == Decimal("1225.00")  # draft stays consistent
    assert draft.status == "DRAFT"


@pytest.mark.django_db
def test_edit_finalised_and_paid_deliveries_are_rejected(
    api_client, farmer, grade, price
):
    created = _record(api_client, farmer, grade).json()
    payout = payouts.build_weekly_payout(farmer, date(2026, 1, 5))
    payouts.finalise_payout(payout)
    url = reverse("api:delivery-detail", args=[created["id"]])

    finalised = api_client.patch(url, {"gross_weight_kg": "50.000"}, format="json")
    assert finalised.status_code == 409
    assert _error(finalised)["code"] == "payout_state_error"

    payouts.mark_payout_paid(Payout.objects.get(pk=payout.pk))
    paid = api_client.patch(url, {"gross_weight_kg": "50.000"}, format="json")
    assert paid.status_code == 409
    assert _error(paid)["code"] == "payout_state_error"

    assert Delivery.objects.get(pk=created["id"]).gross_weight_kg == Decimal("100.000")


# --- Nested corrections -----------------------------------------------------


@pytest.mark.django_db
def test_nested_correction_uses_url_original(api_client, farmer, grade, price):
    delivery = _settled(api_client, farmer, grade)
    response = api_client.post(
        reverse("api:delivery-corrections", args=[delivery["id"]]),
        {"kind": "CREDIT_NOTE", "magnitude": "50.00", "reason": "Quality bonus"},
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["original_delivery"] == delivery["id"]
    assert body["farmer"] == farmer.id  # inherited from the original
    assert body["kind"] == "CREDIT_NOTE"
    assert body["amount"] == "50.00"

    # The original snapshot is untouched.
    original = Delivery.objects.get(pk=delivery["id"])
    assert original.amount == Decimal("2450.00")
    assert original.deduction_kg == Decimal("0.00000")


@pytest.mark.django_db
def test_nested_correction_rejects_client_ownership_and_totals(
    api_client, farmer, other_farmer, grade, price
):
    delivery = _settled(api_client, farmer, grade)
    for field, value in (
        ("farmer", other_farmer.id),
        ("amount", "9999.00"),
        ("original_delivery", delivery["id"]),
        ("correction_magnitude", "50.00"),
    ):
        response = api_client.post(
            reverse("api:delivery-corrections", args=[delivery["id"]]),
            {"kind": "CREDIT_NOTE", "magnitude": "50.00", "reason": "x", field: value},
            format="json",
        )
        assert response.status_code == 400, field
        assert _error(response)["code"] == "protected_field", field
    assert Delivery.objects.filter(original_delivery_id=delivery["id"]).count() == 0


@pytest.mark.django_db
def test_nested_correction_unknown_original(api_client, farmer, grade, price):
    response = api_client.post(
        reverse("api:delivery-corrections", args=[9999]),
        {"kind": "CREDIT_NOTE", "magnitude": "50.00", "reason": "Ghost"},
        format="json",
    )
    assert response.status_code == 404
    assert _error(response)["code"] == "original_not_found"


@pytest.mark.django_db
def test_nested_correction_against_unsettled_is_conflict(
    api_client, farmer, grade, price
):
    created = _record(api_client, farmer, grade).json()
    response = api_client.post(
        reverse("api:delivery-corrections", args=[created["id"]]),
        {"kind": "DEBIT_NOTE", "magnitude": "50.00", "reason": "Premature"},
        format="json",
    )
    assert response.status_code == 409
    assert _error(response)["code"] == "original_not_settled"
