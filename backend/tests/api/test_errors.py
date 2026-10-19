"""M3: the unified API error contract, request IDs and logging."""

import json
import logging
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.db import IntegrityError
from django.urls import reverse

from procurement.api.errors import _database_conflict
from procurement.models import Farmer
from procurement.services import advances

pytestmark = pytest.mark.m3

PAYLOAD = {
    "delivered_on": "2026-01-05",
    "gross_weight_kg": "100.000",
    "moisture_percent": "14.00",
}


def _error(response):
    return response.json()["error"]


def _assert_envelope(response, code):
    body = _error(response)
    assert set(body) == {"code", "message", "details", "request_id"}
    assert body["code"] == code
    assert body["message"]
    assert isinstance(body["details"], dict)
    assert body["request_id"]
    # The request ID is echoed on the response header.
    assert response["X-Request-ID"] == body["request_id"]


# --- Status mapping ---------------------------------------------------------


@pytest.mark.django_db
def test_validation_error_is_400(api_client, farmer):
    response = api_client.post(
        reverse("api:farmer-list"),
        {"name": "Asha", "phone": "not-a-number", "village": "Kolar"},
        format="json",
    )
    assert response.status_code == 400
    _assert_envelope(response, _error(response)["code"])
    assert "phone" in _error(response)["details"]


@pytest.mark.django_db
def test_unknown_resource_is_404(api_client):
    response = api_client.get(reverse("api:farmer-detail", args=[9999]))
    assert response.status_code == 404
    _assert_envelope(response, "farmer_not_found")


@pytest.mark.django_db
def test_duplicate_is_409(api_client, crop, grade, price):
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
    _assert_envelope(response, "price_already_exists")


@pytest.mark.django_db
def test_domain_rejection_is_422(api_client, farmer, grade):
    response = api_client.post(
        reverse("api:delivery-preview"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    )
    assert response.status_code == 422
    _assert_envelope(response, "price_not_found")


@pytest.mark.django_db
def test_unexpected_fault_is_generic_500(api_client, farmer, grade, price, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("secret-review-key-do-not-leak")

    monkeypatch.setattr("procurement.api.views.preview_delivery", boom)
    response = api_client.post(
        reverse("api:delivery-preview"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    )
    assert response.status_code == 500
    _assert_envelope(response, "internal_error")
    assert _error(response)["message"] == "An unexpected error occurred."
    assert "secret-review-key" not in response.content.decode()


# --- Request IDs ------------------------------------------------------------


@pytest.mark.django_db
def test_well_formed_client_request_id_is_preserved(api_client):
    response = api_client.get(
        reverse("api:farmer-list"), HTTP_X_REQUEST_ID="client-request-1234"
    )
    assert response.status_code == 200
    assert response["X-Request-ID"] == "client-request-1234"


@pytest.mark.django_db
def test_malformed_client_request_id_is_replaced(api_client):
    response = api_client.get(
        reverse("api:farmer-detail", args=[9999]), HTTP_X_REQUEST_ID="bad id!"
    )
    assert response.status_code == 404
    request_id = response["X-Request-ID"]
    assert request_id != "bad id!"
    assert len(request_id) == 32
    assert request_id == _error(response)["request_id"]


# --- Logging ----------------------------------------------------------------


@pytest.mark.django_db
def test_domain_rejection_logs_warning_with_request_id(
    api_client, farmer, grade, monkeypatch, caplog
):
    api_logger = logging.getLogger("procurement.api")
    monkeypatch.setattr(api_logger, "propagate", True)
    with caplog.at_level(logging.WARNING):
        response = api_client.post(
            reverse("api:delivery-preview"),
            {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
            format="json",
        )
    record = next(
        r for r in caplog.records if "request.rejected" in r.getMessage()
    )
    assert record.levelno == logging.WARNING
    payload = json.loads(record.getMessage())
    assert payload["request_id"] == response["X-Request-ID"]
    assert payload["code"] == "price_not_found"
    assert payload["status"] == 422
    assert payload["method"] == "POST"
    assert payload["path"] == "/api/v1/deliveries/preview/"
    assert payload["timestamp"]


@pytest.mark.django_db
def test_unexpected_fault_logs_error_with_exception_info(
    api_client, farmer, grade, price, monkeypatch, caplog
):
    def boom(**kwargs):
        raise RuntimeError("boom-detail")

    monkeypatch.setattr("procurement.api.views.preview_delivery", boom)
    api_logger = logging.getLogger("procurement.api")
    monkeypatch.setattr(api_logger, "propagate", True)
    with caplog.at_level(logging.ERROR):
        api_client.post(
            reverse("api:delivery-preview"),
            {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
            format="json",
        )
    record = next(r for r in caplog.records if "request.failed" in r.getMessage())
    assert record.levelno == logging.ERROR
    payload = json.loads(record.getMessage())
    assert payload["exception"] == "RuntimeError"
    assert payload["exception_message"] == "boom-detail"
    assert "traceback" in payload


@pytest.mark.django_db
def test_logs_do_not_contain_body_credentials_or_banking(
    api_client, monkeypatch, caplog
):
    monkeypatch.setattr(
        logging.getLogger("procurement.api"), "propagate", True
    )
    with caplog.at_level(logging.INFO):
        api_client.post(
            reverse("api:farmer-list"),
            {
                "name": "Asha",
                "phone": "9000000001",
                "village": "Kolar",
                "bank_reference": "SECRET-BANK-ACCOUNT",
            },
            format="json",
        )
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "SECRET-BANK-ACCOUNT" not in logged
    assert "9000000001" not in logged


# --- Rollback ---------------------------------------------------------------


@pytest.mark.django_db
def test_unexpected_financial_failure_rolls_back(api_client, farmer, grade, price, monkeypatch):
    from django.db import transaction

    advances.post_advance(farmer, Decimal("500.00"), date(2026, 1, 5))
    api_client.post(
        reverse("api:delivery-list"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    )
    payout_id = (
        api_client.post(
            reverse("api:payout-generate"),
            {"farmer": farmer.id, "week_start": "2026-01-05"},
            format="json",
        ).json()["payout"]["id"]
    )

    def boom(payout):
        with transaction.atomic():
            Farmer.objects.filter(pk=payout.farmer_id).update(
                outstanding_advance=Decimal("0.00")
            )
            raise RuntimeError("failure after a write")

    monkeypatch.setattr("procurement.api.views.finalise_payout", boom)
    response = api_client.post(reverse("api:payout-finalise", args=[payout_id]))

    assert response.status_code == 500
    _assert_envelope(response, "internal_error")
    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("500.00")


# --- Database conflict mapping ----------------------------------------------


class _FakeDbError(Exception):
    def __init__(self, sqlstate, constraint):
        super().__init__("db error")
        self.sqlstate = sqlstate
        self.diag = SimpleNamespace(constraint_name=constraint)


def _integrity_error(sqlstate=None, constraint=None):
    exc = IntegrityError("db error")
    exc.__cause__ = _FakeDbError(sqlstate, constraint)
    return exc


def test_known_unique_constraint_maps_to_specific_409():
    code, status_code, _ = _database_conflict(
        _integrity_error("23505", "payout_one_draft_farmer_week")
    )
    assert code == "payout_state_error"
    assert status_code == 409


def test_unknown_unique_violation_maps_to_generic_409():
    code, status_code, _ = _database_conflict(_integrity_error("23505", "some_unique"))
    assert code == "conflict"
    assert status_code == 409


def test_check_violation_maps_to_422():
    code, status_code, _ = _database_conflict(
        _integrity_error("23514", "farmer_outstanding_nonnegative")
    )
    assert code == "invalid_state"
    assert status_code == 422


def test_foreign_key_violation_maps_to_409():
    code, status_code, _ = _database_conflict(_integrity_error("23503", None))
    assert code == "referenced_record"
    assert status_code == 409


def test_not_null_violation_is_not_misreported_as_conflict():
    assert _database_conflict(_integrity_error("23502", None)) is None
