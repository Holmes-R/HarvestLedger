"""M3: advance posting, listing and reconciliation endpoints."""

from decimal import Decimal

import pytest
from django.urls import reverse

from procurement.models import Advance, Farmer

pytestmark = pytest.mark.m3


def _error(response):
    return response.json()["error"]


@pytest.mark.django_db
def test_post_advance_updates_balance(api_client, farmer):
    response = api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "500.00", "given_on": "2026-01-05"},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["amount"] == "500.00"
    farmer.refresh_from_db()
    assert str(farmer.outstanding_advance) == "500.00"


@pytest.mark.django_db
def test_post_non_positive_advance_is_rejected(api_client, farmer):
    response = api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "0.00", "given_on": "2026-01-05"},
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "not_positive"
    assert Farmer.objects.get(pk=farmer.id).outstanding_advance == 0


@pytest.mark.django_db
def test_post_advance_missing_farmer_is_not_found(api_client):
    response = api_client.post(
        reverse("api:advance-list"),
        {"farmer": 9999, "amount": "500.00", "given_on": "2026-01-05"},
        format="json",
    )
    assert response.status_code == 404
    assert _error(response)["code"] == "farmer_not_found"


@pytest.mark.django_db
def test_advance_list_filters_by_farmer(api_client, farmer, other_farmer):
    for who in (farmer, other_farmer, farmer):
        api_client.post(
            reverse("api:advance-list"),
            {"farmer": who.id, "amount": "100.00", "given_on": "2026-01-05"},
            format="json",
        )
    response = api_client.get(reverse("api:advance-list"), {"farmer": farmer.id})
    assert response.status_code == 200
    assert response.json()["count"] == 2


@pytest.mark.django_db
def test_advance_detail_not_found(api_client):
    response = api_client.get(reverse("api:advance-detail", args=[9999]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_reconciliation_endpoint(api_client, farmer):
    api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "500.00", "given_on": "2026-01-05"},
        format="json",
    )
    response = api_client.get(reverse("api:advance-reconciliation", args=[farmer.id]))
    assert response.status_code == 200
    body = response.json()
    assert body["total_advances"] == "500.00"
    assert body["stored_outstanding"] == "500.00"
    assert body["is_reconciled"] is True


@pytest.mark.django_db
def test_reconciliation_missing_farmer_is_not_found(api_client):
    response = api_client.get(reverse("api:advance-reconciliation", args=[9999]))
    assert response.status_code == 404
    assert _error(response)["code"] == "farmer_not_found"


@pytest.mark.django_db
def test_post_advance_returns_decimal_string(api_client, farmer):
    response = api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "250.50", "given_on": "2026-01-05"},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["amount"] == "250.50"
    assert isinstance(response.json()["amount"], str)


@pytest.mark.django_db
def test_post_advance_missing_farmer_field(api_client, db):
    response = api_client.post(
        reverse("api:advance-list"),
        {"amount": "100.00", "given_on": "2026-01-05"},
        format="json",
    )
    assert response.status_code == 400
    assert "farmer" in _error(response)["details"]


@pytest.mark.django_db
def test_post_advance_rejects_over_precise_amount(api_client, farmer):
    before = Farmer.objects.get(pk=farmer.id).outstanding_advance
    response = api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "10.001", "given_on": "2026-01-05"},
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "max_decimal_places"
    assert Advance.objects.count() == 0
    assert Farmer.objects.get(pk=farmer.id).outstanding_advance == before


@pytest.mark.django_db
def test_post_advance_rejects_over_capacity_amount(api_client, farmer):
    response = api_client.post(
        reverse("api:advance-list"),
        {
            "farmer": farmer.id,
            "amount": "10000000000000.00",
            "given_on": "2026-01-05",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "amount" in _error(response)["details"]
    assert Advance.objects.count() == 0
    assert Farmer.objects.get(pk=farmer.id).outstanding_advance == Decimal("0.00")


@pytest.mark.django_db
def test_post_advance_rejects_client_supplied_balance(api_client, farmer):
    response = api_client.post(
        reverse("api:advance-list"),
        {
            "farmer": farmer.id,
            "amount": "100.00",
            "given_on": "2026-01-05",
            "outstanding_advance": "9999.00",
        },
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "protected_field"
    assert Farmer.objects.get(pk=farmer.id).outstanding_advance == Decimal("0.00")


@pytest.mark.django_db
def test_same_day_advances_are_distinct_and_all_counted(api_client, farmer):
    ids = []
    for _ in range(3):
        response = api_client.post(
            reverse("api:advance-list"),
            {"farmer": farmer.id, "amount": "100.00", "given_on": "2026-01-05"},
            format="json",
        )
        assert response.status_code == 201
        ids.append(response.json()["id"])
    assert len(set(ids)) == 3  # same (farmer, date) is not a dedup key
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("300.00")

    ledger = api_client.get(reverse("api:farmer-ledger", args=[farmer.id]))
    assert ledger.json()["summary"]["total_advances"] == "300.00"


@pytest.mark.django_db
def test_advance_has_no_edit_or_delete(api_client, farmer):
    created = api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "100.00", "given_on": "2026-01-05"},
        format="json",
    ).json()
    url = reverse("api:advance-detail", args=[created["id"]])
    assert api_client.patch(url, {"amount": "1.00"}, format="json").status_code == 405
    assert api_client.delete(url).status_code == 405
    assert Advance.objects.get(pk=created["id"]).amount == Decimal("100.00")


@pytest.mark.django_db
def test_post_advance_rolls_back_on_unexpected_failure(api_client, farmer, monkeypatch):
    api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "100.00", "given_on": "2026-01-05"},
        format="json",
    )

    # The advance row is created before the balance is persisted; a failure while
    # saving the farmer must roll the whole posting back, leaving both the row
    # count and the balance as they were.
    def boom(self, *args, **kwargs):
        raise RuntimeError("failure after the advance row was written")

    monkeypatch.setattr(Farmer, "save", boom)
    response = api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "250.00", "given_on": "2026-01-06"},
        format="json",
    )
    assert response.status_code == 500
    assert _error(response)["code"] == "internal_error"
    assert Advance.objects.count() == 1  # the failed advance was not persisted
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("100.00")
