"""M3: advance posting, listing and reconciliation endpoints."""

import pytest
from django.urls import reverse

from procurement.models import Farmer

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
    response = api_client.get(
        reverse("api:advance-reconciliation", args=[farmer.id])
    )
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
