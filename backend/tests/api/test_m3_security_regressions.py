"""Regression checks for M3 error handling, CORS, and unmatched API routes."""

import json
import logging
from datetime import date
from decimal import Decimal

import pytest
from django.db import transaction
from django.test import override_settings
from django.urls import reverse

from procurement.models import Delivery, Farmer, Payout
from procurement.services import advances

pytestmark = pytest.mark.m3

DELIVERY = {
    "delivered_on": "2026-01-05",
    "gross_weight_kg": "100.000",
    "moisture_percent": "14.00",
}


@pytest.mark.django_db
def test_unexpected_error_logs_only_safe_diagnostics_and_rolls_back(
    api_client, farmer, grade, price, monkeypatch, caplog
):
    """Exception arguments and chained messages must never enter any log handler."""
    advances.post_advance(farmer, Decimal("500.00"), date(2026, 1, 5))
    recorded = api_client.post(
        reverse("api:delivery-list"),
        {**DELIVERY, "farmer": farmer.pk, "crop_grade": grade.pk},
        format="json",
    )
    assert recorded.status_code == 201
    payout_id = api_client.post(
        reverse("api:payout-generate"),
        {"farmer": farmer.pk, "week_start": "2026-01-05"},
        format="json",
    ).json()["payout"]["id"]
    before = Payout.objects.get(pk=payout_id)
    membership = list(before.deliveries.values_list("pk", flat=True))
    financials = (
        before.status,
        before.gross_amount,
        before.advance_deduction,
        before.net_amount,
    )
    sentinels = (
        "BANK_REFERENCE_PRIVATE_SENTINEL",
        "DATABASE_PASSWORD_PRIVATE_SENTINEL",
        "REVIEW_KEY_PRIVATE_SENTINEL",
        "CHAINED_CAUSE_PRIVATE_SENTINEL",
    )

    def fail_after_write(payout):
        with transaction.atomic():
            Farmer.objects.filter(pk=payout.farmer_id).update(
                outstanding_advance=Decimal("0.00")
            )
            try:
                raise ValueError(sentinels[3])
            except ValueError as cause:
                raise RuntimeError(" ".join(sentinels[:3])) from cause

    monkeypatch.setattr("procurement.api.views.finalise_payout", fail_after_write)
    monkeypatch.setattr(logging.getLogger("procurement.api"), "propagate", True)
    with (
        override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"]),
        caplog.at_level(logging.ERROR),
    ):
        response = api_client.post(
            reverse("api:payout-finalise", args=[payout_id]),
            HTTP_X_REQUEST_ID="m3-safe-error-1234",
        )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "details": {},
            "request_id": "m3-safe-error-1234",
        }
    }
    assert response["X-Request-ID"] == "m3-safe-error-1234"
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert all(sentinel not in logged for sentinel in sentinels)
    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "procurement.api" and "request.failed" in record.getMessage()
    ]
    assert events
    assert all(event["request_id"] == response["X-Request-ID"] for event in events)
    assert all(event["code"] == "internal_error" for event in events)
    assert all(event["exception"] == "RuntimeError" for event in events)
    assert all(event["status"] == 500 for event in events)
    farmer.refresh_from_db()
    payout = Payout.objects.get(pk=payout_id)
    assert farmer.outstanding_advance == Decimal("500.00")
    assert (
        payout.status,
        payout.gross_amount,
        payout.advance_deduction,
        payout.net_amount,
    ) == financials
    assert list(payout.deliveries.values_list("pk", flat=True)) == membership
    assert Delivery.objects.get(pk=recorded.json()["id"]).payout_id == payout_id


@override_settings(CORS_ALLOWED_ORIGINS=["http://localhost:5173"])
def test_preflight_allows_documented_headers_without_reflection(client):
    headers = "content-type,x-request-id,x-test-clock,x-review-key"
    allowed = client.options(
        reverse("api:delivery-list"),
        HTTP_ORIGIN="http://localhost:5173",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS=headers,
    )
    assert allowed.status_code == 200
    assert allowed["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "POST" in allowed["Access-Control-Allow-Methods"]
    offered = {
        part.strip().lower()
        for part in allowed["Access-Control-Allow-Headers"].split(",")
    }
    assert set(headers.split(",")) <= offered
    assert "x-unlisted-secret" not in offered

    disallowed = client.options(
        reverse("api:delivery-list"),
        HTTP_ORIGIN="http://untrusted.example",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS=headers,
    )
    assert "Access-Control-Allow-Origin" not in disallowed

    actual = client.get(reverse("api:health"), HTTP_ORIGIN="http://localhost:5173")
    assert actual.status_code == 200
    assert actual["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "x-request-id" in actual["Access-Control-Expose-Headers"].lower()
    assert actual["X-Request-ID"]

    # A CORS allowlist only enables browser transport; the reviewer-clock gate
    # still rejects a clock override until both its flag and key allow it.
    clock_headers = {
        "HTTP_ORIGIN": "http://localhost:5173",
        "HTTP_X_TEST_CLOCK": "2026-01-05T00:15:00+05:30",
        "HTTP_X_REVIEW_KEY": "wrong-key",
    }
    with override_settings(ALLOW_REVIEW_CLOCK=False, REVIEW_CLOCK_KEY="configured-key"):
        disabled = client.post(reverse("api:delivery-preview"), {}, **clock_headers)
    assert disabled.status_code == 403
    assert disabled.json()["error"]["code"] == "review_clock_disabled"
    with override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY="configured-key"):
        unauthorized = client.post(reverse("api:delivery-preview"), {}, **clock_headers)
    assert unauthorized.status_code == 403
    assert unauthorized.json()["error"]["code"] == "review_clock_unauthorized"


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"])
@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
def test_unmatched_api_route_returns_json_404_with_request_id(client, method):
    response = client.generic(
        method,
        "/api/v1/unknown-resource/",
        b"",
        content_type="application/json",
        HTTP_X_REQUEST_ID="m3-unknown-route-1234",
    )
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "The requested API route was not found.",
            "details": {},
            "request_id": "m3-unknown-route-1234",
        }
    }
    assert response["X-Request-ID"] == response.json()["error"]["request_id"]


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
def test_existing_route_method_and_non_api_routes_keep_their_contract(client):
    wrong_method = client.put(
        reverse("api:farmer-list"), {}, content_type="application/json"
    )
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["request_id"] == wrong_method["X-Request-ID"]
    assert client.get("/api/schema/").status_code == 200
    assert client.get("/api/docs/").status_code == 200
    assert client.get("/admin/login/").status_code == 200
    outside = client.get("/unmatched-outside-api/")
    assert outside.status_code == 404
    assert outside["Content-Type"].startswith("text/html")
