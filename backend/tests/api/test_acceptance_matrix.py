"""M3 acceptance matrix (API01-API12) exercised as real DRF request/response.

Every case drives the real URL router, DRF serializers/views, middleware, the M2
service layer and the isolated PostgreSQL test database. The M2 behaviour under
test is never mocked: the only injection is a deliberate malfunction at the view
boundary, used to prove the API10 unexpected-failure path and its transactional
rollback.

* API01 valid requests for every Core endpoint (status + response + persisted)
* API02 missing fields / wrong types (consistent errors, no partial writes)
* API03 unknown resources (documented not-found behaviour)
* API04 protected field writes (amount, applied rate, balance, membership, status)
* API05 duplicate prices and finalised edits (409 + stable codes)
* API06 preview mutates no Delivery, Payout, Advance or balance
* API07 pagination/filtering (bounded, deterministic, controlled invalid errors)
* API08 reviewer clock (valid / disabled / malformed / wrong key)
* API09 concurrent clocks (no cross-request leakage)
* API10 unexpected failure (generic 500, correlated log, financial rollback)
* API11 mark paid before finalisation (409, no financial/state change)
* API12 crop/grade changes preserve historical delivery snapshots
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from django.db import transaction
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import reverse

from procurement.api.middleware import ReviewClockMiddleware
from procurement.clock import get_clock
from procurement.models import (
    Advance,
    Crop,
    Delivery,
    Farmer,
    Payout,
    PriceListEntry,
)

pytestmark = pytest.mark.m3

DAY = "2026-01-05"  # Monday; the price fixture is effective 2026-01-01
DELIVERY = {
    "delivered_on": DAY,
    "gross_weight_kg": "100.000",
    "moisture_percent": "14.00",
}
CLOCK_KEY = "demo-review-key-123"


def _error(response):
    return response.json()["error"]


def _record(api_client, farmer, grade, **overrides):
    payload = {**DELIVERY, "farmer": farmer.id, "crop_grade": grade.id, **overrides}
    return api_client.post(reverse("api:delivery-list"), payload, format="json")


def _generate(api_client, farmer, week_start=DAY):
    return api_client.post(
        reverse("api:payout-generate"),
        {"farmer": farmer.id, "week_start": week_start},
        format="json",
    )


# --- API01 ------------------------------------------------------------------


@pytest.mark.django_db
def test_api01_valid_requests_for_every_core_endpoint(
    api_client, farmer, other_farmer, grade, price
):
    crop = grade.crop
    farmer_id = farmer.id

    # System + reference reads.
    assert api_client.get(reverse("api:health")).status_code == 200
    assert api_client.get(reverse("api:farmer-list")).status_code == 200
    assert api_client.get(reverse("api:crop-list")).status_code == 200
    assert api_client.get(reverse("api:grade-list")).status_code == 200
    assert api_client.get(reverse("api:price-list")).status_code == 200

    # Farmer create / detail / patch.
    created = api_client.post(
        reverse("api:farmer-list"),
        {"name": "Chandra", "phone": "9000000003", "village": "Mandya"},
        format="json",
    )
    assert created.status_code == 201
    assert Farmer.objects.filter(pk=created.json()["id"]).exists()
    assert (
        api_client.get(reverse("api:farmer-detail", args=[farmer_id])).status_code
        == 200
    )
    patched = api_client.patch(
        reverse("api:farmer-detail", args=[farmer_id]),
        {"village": "Kolar Gold Fields"},
        format="json",
    )
    assert patched.status_code == 200
    farmer.refresh_from_db()
    assert farmer.village == "Kolar Gold Fields"

    # Crop create / detail / patch.
    new_crop = api_client.post(
        reverse("api:crop-list"),
        {
            "name": "Ragi",
            "moisture_threshold": "12.00",
            "max_moisture": "18.00",
            "allowed_grades": ["A"],
        },
        format="json",
    )
    assert new_crop.status_code == 201
    assert Crop.objects.filter(pk=new_crop.json()["id"]).exists()
    assert api_client.get(reverse("api:crop-detail", args=[crop.id])).status_code == 200
    assert (
        api_client.patch(
            reverse("api:crop-detail", args=[crop.id]),
            {"max_moisture": "22.00"},
            format="json",
        ).status_code
        == 200
    )

    # Price append.
    entry = api_client.post(
        reverse("api:price-list"),
        {
            "crop": crop.id,
            "grade": "A",
            "price_per_kg": "25.00",
            "effective_from": "2026-02-01",
        },
        format="json",
    )
    assert entry.status_code == 201
    assert PriceListEntry.objects.filter(pk=entry.json()["id"]).exists()

    # Preview.
    preview = api_client.post(
        reverse("api:delivery-preview"),
        {**DELIVERY, "farmer": farmer_id, "crop_grade": grade.id},
        format="json",
    )
    assert preview.status_code == 200
    assert preview.json()["amount"] == "2450.00"

    # Delivery create / detail / edit.
    recorded = _record(api_client, farmer, grade)
    assert recorded.status_code == 201
    delivery_id = recorded.json()["id"]
    assert Delivery.objects.filter(pk=delivery_id).exists()
    assert (
        api_client.get(reverse("api:delivery-detail", args=[delivery_id])).status_code
        == 200
    )
    edited = api_client.patch(
        reverse("api:delivery-detail", args=[delivery_id]),
        {"gross_weight_kg": "120.000"},
        format="json",
    )
    assert edited.status_code == 200
    assert edited.json()["amount"] == "2940.00"

    # Advance create / list / detail / reconciliation.
    advance = api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer_id, "amount": "500.00", "given_on": DAY},
        format="json",
    )
    assert advance.status_code == 201
    assert Advance.objects.filter(pk=advance.json()["id"]).exists()
    assert (
        api_client.get(
            reverse("api:advance-detail", args=[advance.json()["id"]])
        ).status_code
        == 200
    )
    assert api_client.get(reverse("api:advance-list")).status_code == 200
    reconciliation = api_client.get(
        reverse("api:advance-reconciliation", args=[farmer_id])
    )
    assert reconciliation.status_code == 200
    assert reconciliation.json()["is_reconciled"] is True

    # Payout generate / list / detail / finalise / mark-paid.
    generated = _generate(api_client, farmer)
    assert generated.status_code == 201
    payout_id = generated.json()["payout"]["id"]
    assert api_client.get(reverse("api:payout-list")).status_code == 200
    assert (
        api_client.get(reverse("api:payout-detail", args=[payout_id])).status_code
        == 200
    )
    finalised = api_client.post(reverse("api:payout-finalise", args=[payout_id]))
    assert finalised.status_code == 200
    assert finalised.json()["status"] == "FINALISED"
    paid = api_client.post(reverse("api:payout-mark-paid", args=[payout_id]))
    assert paid.status_code == 200
    assert paid.json()["status"] == "PAID"
    assert Payout.objects.get(pk=payout_id).paid_at is not None

    # Corrections: list / create / detail and the nested delivery route.
    assert api_client.get(reverse("api:correction-list")).status_code == 200
    correction = api_client.post(
        reverse("api:correction-list"),
        {
            "original_delivery": delivery_id,
            "kind": "CREDIT_NOTE",
            "magnitude": "10.00",
            "reason": "Returned to farmer",
        },
        format="json",
    )
    assert correction.status_code == 201, correction.json()
    correction_id = correction.json()["id"]
    assert correction.json()["kind"] == "CREDIT_NOTE"
    assert (
        api_client.get(
            reverse("api:correction-detail", args=[correction_id])
        ).status_code
        == 200
    )
    nested = api_client.post(
        reverse("api:delivery-corrections", args=[delivery_id]),
        {"kind": "DEBIT_NOTE", "magnitude": "5.00", "reason": "Short weight"},
        format="json",
    )
    assert nested.status_code == 201

    # Ledger.
    ledger = api_client.get(reverse("api:farmer-ledger", args=[farmer_id]))
    assert ledger.status_code == 200
    assert "summary" in ledger.json()


@pytest.mark.django_db
def test_api01_read_only_routes_reject_mutations(api_client, farmer, grade, price):
    recorded = _record(api_client, farmer, grade)
    assert recorded.status_code == 201
    delivery_id = recorded.json()["id"]
    assert (
        api_client.post(reverse("api:payout-list"), {}, format="json").status_code
        == 405
    )
    assert (
        api_client.patch(reverse("api:payout-detail", args=[9999])).status_code == 405
    )
    assert (
        api_client.delete(
            reverse("api:delivery-detail", args=[delivery_id])
        ).status_code
        == 405
    )
    assert (
        api_client.patch(reverse("api:advance-detail", args=[9999])).status_code == 405
    )
    assert (
        api_client.delete(reverse("api:farmer-detail", args=[farmer.id])).status_code
        == 405
    )


# --- API02 ------------------------------------------------------------------


@pytest.mark.django_db
def test_api02_missing_fields_and_wrong_types_leave_no_partial_writes(
    api_client, farmer, grade, price
):
    before = (
        Delivery.objects.count(),
        Payout.objects.count(),
        Advance.objects.count(),
        Farmer.objects.count(),
    )

    missing = api_client.post(
        reverse("api:delivery-list"),
        {"farmer": farmer.id, "crop_grade": grade.id, "delivered_on": DAY},
        format="json",
    )
    assert missing.status_code == 400
    body = _error(missing)
    assert set(body) == {"code", "message", "details", "request_id"}
    assert {"gross_weight_kg", "moisture_percent"} <= set(body["details"])

    wrong_type = api_client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.id, "amount": "not-money", "given_on": DAY},
        format="json",
    )
    assert wrong_type.status_code == 400
    assert "amount" in _error(wrong_type)["details"]

    bad_date = api_client.post(
        reverse("api:delivery-list"),
        {
            **DELIVERY,
            "farmer": farmer.id,
            "crop_grade": grade.id,
            "delivered_on": "05-01-2026",
        },
        format="json",
    )
    assert bad_date.status_code == 400
    assert "delivered_on" in _error(bad_date)["details"]

    after = (
        Delivery.objects.count(),
        Payout.objects.count(),
        Advance.objects.count(),
        Farmer.objects.count(),
    )
    assert before == after


# --- API03 ------------------------------------------------------------------


@pytest.mark.django_db
def test_api03_unknown_resources_are_documented_not_found(
    api_client, farmer, grade, price
):
    crop = grade.crop
    assert (
        _error(api_client.get(reverse("api:farmer-detail", args=[9999])))["code"]
        == "farmer_not_found"
    )
    assert (
        _error(api_client.get(reverse("api:crop-detail", args=[9999])))["code"]
        == "crop_not_found"
    )
    for route in ("api:delivery-detail", "api:advance-detail", "api:correction-detail"):
        assert (
            _error(api_client.get(reverse(route, args=[9999])))["code"] == "not_found"
        )
    assert (
        _error(api_client.get(reverse("api:payout-detail", args=[9999])))["code"]
        == "not_found"
    )
    assert (
        _error(api_client.get(reverse("api:farmer-ledger", args=[9999])))["code"]
        == "farmer_not_found"
    )
    assert (
        _error(api_client.get(reverse("api:advance-reconciliation", args=[9999])))[
            "code"
        ]
        == "farmer_not_found"
    )

    unknown_farmer = api_client.post(
        reverse("api:delivery-list"),
        {**DELIVERY, "farmer": 9999, "crop_grade": grade.id},
        format="json",
    )
    assert unknown_farmer.status_code == 404
    assert _error(unknown_farmer)["code"] == "farmer_not_found"

    unknown_grade = api_client.post(
        reverse("api:delivery-list"),
        {**DELIVERY, "farmer": farmer.id, "crop_grade": 9999},
        format="json",
    )
    assert unknown_grade.status_code == 404
    assert _error(unknown_grade)["code"] == "crop_grade_not_found"

    unknown_crop = api_client.post(
        reverse("api:price-list"),
        {
            "crop": 9999,
            "grade": "A",
            "price_per_kg": "25.00",
            "effective_from": "2026-02-01",
        },
        format="json",
    )
    assert unknown_crop.status_code == 404
    assert _error(unknown_crop)["code"] == "crop_not_found"

    unknown_original = api_client.post(
        reverse("api:correction-list"),
        {
            "original_delivery": 9999,
            "kind": "CREDIT_NOTE",
            "magnitude": "1.00",
            "reason": "x",
        },
        format="json",
    )
    assert unknown_original.status_code == 404
    assert _error(unknown_original)["code"] == "original_not_found"

    assert crop is not None  # the crop/grade fixtures above are real rows


# --- API04 ------------------------------------------------------------------


@pytest.mark.django_db
def test_api04_protected_field_writes_are_rejected(api_client, farmer, grade, price):
    forbidden = {
        "amount": "9999.00",
        "applied_price": "999.00",
        "net_kg": "999.00000",
        "payout": 7,
    }
    for field, value in forbidden.items():
        response = _record(api_client, farmer, grade, **{field: value})
        assert response.status_code == 400, field
        assert _error(response)["code"] == "protected_field", field

    assert Delivery.objects.count() == 0

    balance = api_client.patch(
        reverse("api:farmer-detail", args=[farmer.id]),
        {"outstanding_advance": "1000.00"},
        format="json",
    )
    assert balance.status_code == 400
    assert _error(balance)["code"] == "protected_field"

    # A payout's membership, status and totals are refused, never silently set.
    recorded = _record(api_client, farmer, grade)
    assert recorded.status_code == 201
    generated = _generate(api_client, farmer)
    assert generated.status_code == 201
    payout_id = generated.json()["payout"]["id"]
    forged = api_client.post(
        reverse("api:payout-generate"),
        {
            "farmer": farmer.id,
            "week_start": DAY,
            "status": "PAID",
            "net_amount": "0.01",
        },
        format="json",
    )
    assert forged.status_code == 400
    assert _error(forged)["code"] == "protected_field"
    assert Payout.objects.get(pk=payout_id).status == "DRAFT"

    # The status cannot be driven through a generic mutation route either.
    generic = api_client.patch(
        reverse("api:payout-detail", args=[payout_id]),
        {"status": "PAID"},
        format="json",
    )
    assert generic.status_code == 405
    assert Payout.objects.get(pk=payout_id).status == "DRAFT"


# --- API05 ------------------------------------------------------------------


@pytest.mark.django_db
def test_api05_duplicate_prices_and_finalised_edits_are_conflicts(
    api_client, farmer, grade, price
):
    duplicate = api_client.post(
        reverse("api:price-list"),
        {
            "crop": grade.crop_id,
            "grade": "A",
            "price_per_kg": "30.00",
            "effective_from": "2026-01-01",
        },
        format="json",
    )
    assert duplicate.status_code == 409
    assert _error(duplicate)["code"] == "price_already_exists"

    recorded = _record(api_client, farmer, grade)
    delivery_id = recorded.json()["id"]
    payout_id = _generate(api_client, farmer).json()["payout"]["id"]
    assert (
        api_client.post(reverse("api:payout-finalise", args=[payout_id])).status_code
        == 200
    )

    settled_edit = api_client.patch(
        reverse("api:delivery-detail", args=[delivery_id]),
        {"gross_weight_kg": "150.000"},
        format="json",
    )
    assert settled_edit.status_code == 409
    assert _error(settled_edit)["code"] == "payout_state_error"
    assert Delivery.objects.get(pk=delivery_id).gross_weight_kg == Decimal("100.000")


# --- API06 ------------------------------------------------------------------


@pytest.mark.django_db
def test_api06_preview_mutates_nothing(api_client, farmer, grade, price):
    before = (
        Delivery.objects.count(),
        Payout.objects.count(),
        Advance.objects.count(),
        farmer.outstanding_advance,
    )
    response = api_client.post(
        reverse("api:delivery-preview"),
        {**DELIVERY, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["amount"] == "2450.00"
    farmer.refresh_from_db()
    after = (
        Delivery.objects.count(),
        Payout.objects.count(),
        Advance.objects.count(),
        farmer.outstanding_advance,
    )
    assert before == after


# --- API07 ------------------------------------------------------------------


@pytest.mark.django_db
def test_api07_pagination_filtering_and_invalid_errors(
    api_client, farmer, grade, price
):
    for index in range(25):
        _record(api_client, farmer, grade, delivered_on=f"2026-01-{5 + index % 20:02d}")

    first_page = api_client.get(reverse("api:delivery-list")).json()
    assert first_page["count"] == 25
    assert len(first_page["results"]) == 20
    assert first_page["next"] is not None

    capped = api_client.get(reverse("api:delivery-list"), {"page_size": 1000}).json()
    assert len(capped["results"]) == 25

    second_page = api_client.get(reverse("api:delivery-list"), {"page": 2}).json()
    first_ids = [row["id"] for row in first_page["results"]]
    second_ids = [row["id"] for row in second_page["results"]]
    assert set(first_ids).isdisjoint(second_ids)
    assert len(first_ids) + len(second_ids) == 25

    assert api_client.get(reverse("api:delivery-list"), {"page": 99}).status_code == 404
    bad_ordering = api_client.get(reverse("api:delivery-list"), {"ordering": "secret"})
    assert bad_ordering.status_code == 400
    assert _error(bad_ordering)["code"] == "invalid"
    reversed_range = api_client.get(
        reverse("api:delivery-list"), {"from": "2026-02-01", "to": "2026-01-01"}
    )
    assert reversed_range.status_code == 400
    assert _error(reversed_range)["code"] == "invalid"


# --- API08 / API09 ----------------------------------------------------------

CLOCK = "2026-12-31T23:00:00+05:30"
CLOCK_DATE = "2026-12-31"


def _preview_with_clock(api_client, farmer, grade, clock=None, key=None):
    headers = {}
    if clock is not None:
        headers["HTTP_X_TEST_CLOCK"] = clock
    if key is not None:
        headers["HTTP_X_REVIEW_KEY"] = key
    return api_client.post(
        reverse("api:delivery-preview"),
        {**DELIVERY, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
        **headers,
    )


@pytest.mark.django_db
@override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY=CLOCK_KEY)
def test_api08_reviewer_clock_valid_and_rejected_scenarios(
    api_client, farmer, grade, price
):
    valid = _preview_with_clock(api_client, farmer, grade, clock=CLOCK, key=CLOCK_KEY)
    assert valid.status_code == 200
    assert valid.json()["business_date"] == CLOCK_DATE

    with override_settings(ALLOW_REVIEW_CLOCK=False):
        off = _preview_with_clock(api_client, farmer, grade, clock=CLOCK, key=CLOCK_KEY)
    assert off.status_code == 403
    assert _error(off)["code"] == "review_clock_disabled"

    unauthorised = _preview_with_clock(
        api_client, farmer, grade, clock=CLOCK, key="wrong"
    )
    assert unauthorised.status_code == 403
    assert _error(unauthorised)["code"] == "review_clock_unauthorized"

    malformed = _preview_with_clock(
        api_client, farmer, grade, clock="not-a-time", key=CLOCK_KEY
    )
    assert malformed.status_code == 400
    assert _error(malformed)["code"] == "review_clock_invalid"

    naive = _preview_with_clock(
        api_client, farmer, grade, clock="2026-03-16T00:30:00", key=CLOCK_KEY
    )
    assert naive.status_code == 400
    assert _error(naive)["code"] == "review_clock_invalid"


@override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY=CLOCK_KEY)
def test_api09_concurrent_clocks_do_not_leak():
    factory = RequestFactory()
    barrier = Barrier(2)
    seen = {}

    def run(label, clock, expected):
        def get_response(_request):
            barrier.wait(timeout=10)
            seen[label] = get_clock().today().isoformat()
            return HttpResponse("ok")

        request = factory.get(
            "/api/v1/deliveries/preview/",
            HTTP_X_TEST_CLOCK=clock,
            HTTP_X_REVIEW_KEY=CLOCK_KEY,
        )
        ReviewClockMiddleware(get_response)(request)
        assert seen[label] == expected

    real_today = get_clock().today().isoformat()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, "a", "2026-01-05T12:00:00+05:30", "2026-01-05")
        second = pool.submit(run, "b", "2027-02-08T12:00:00+05:30", "2027-02-08")
        first.result()
        second.result()

    assert seen == {"a": "2026-01-05", "b": "2027-02-08"}
    assert get_clock().today().isoformat() == real_today


# --- API10 ------------------------------------------------------------------


@pytest.mark.django_db
def test_api10_unexpected_failure_500_correlated_log_and_rollback(
    api_client, farmer, grade, price, monkeypatch, caplog
):
    assert (
        api_client.post(
            reverse("api:advance-list"),
            {"farmer": farmer.id, "amount": "500.00", "given_on": DAY},
            format="json",
        ).status_code
        == 201
    )
    assert _record(api_client, farmer, grade).status_code == 201
    payout_id = _generate(api_client, farmer).json()["payout"]["id"]

    def boom(payout):
        with transaction.atomic():
            Farmer.objects.filter(pk=payout.farmer_id).update(
                outstanding_advance=Decimal("0.00")
            )
            raise RuntimeError("boom-after-financial-write")

    monkeypatch.setattr("procurement.api.views.finalise_payout", boom)
    api_logger = logging.getLogger("procurement.api")
    monkeypatch.setattr(api_logger, "propagate", True)
    with caplog.at_level(logging.ERROR):
        response = api_client.post(reverse("api:payout-finalise", args=[payout_id]))

    assert response.status_code == 500
    error = _error(response)
    assert error["code"] == "internal_error"
    assert error["message"] == "An unexpected error occurred."
    assert "boom-after-financial-write" not in response.content.decode()

    record = next(r for r in caplog.records if "request.failed" in r.getMessage())
    payload = json.loads(record.getMessage())
    assert payload["request_id"] == response["X-Request-ID"]
    assert payload["status"] == 500
    assert payload["exception"] == "RuntimeError"
    assert "exception_message" not in payload
    assert "traceback" not in payload
    assert payload["frames"]

    farmer.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("500.00")
    assert Payout.objects.get(pk=payout_id).status == "DRAFT"


# --- API11 ------------------------------------------------------------------


@pytest.mark.django_db
def test_api11_mark_paid_before_finalisation_is_conflict_without_changes(
    api_client, farmer, grade, price
):
    assert (
        api_client.post(
            reverse("api:advance-list"),
            {"farmer": farmer.id, "amount": "500.00", "given_on": DAY},
            format="json",
        ).status_code
        == 201
    )
    assert _record(api_client, farmer, grade).status_code == 201
    payout_id = _generate(api_client, farmer).json()["payout"]["id"]
    draft = Payout.objects.get(pk=payout_id)
    assert draft.status == "DRAFT"
    assert draft.paid_at is None

    response = api_client.post(reverse("api:payout-mark-paid", args=[payout_id]))
    assert response.status_code == 409
    assert _error(response)["code"] == "payout_state_error"

    draft.refresh_from_db()
    farmer.refresh_from_db()
    assert draft.status == "DRAFT"
    assert draft.paid_at is None
    assert draft.advance_deduction == Decimal("0.00")
    assert farmer.outstanding_advance == Decimal("500.00")


# --- API12 ------------------------------------------------------------------


@pytest.mark.django_db
def test_api12_crop_and_grade_changes_preserve_delivery_snapshots(
    api_client, farmer, grade, price
):
    recorded = _record(api_client, farmer, grade)
    assert recorded.status_code == 201
    snapshot = recorded.json()

    # Change the crop's moisture configuration and add a new grade.
    assert (
        api_client.patch(
            reverse("api:crop-detail", args=[grade.crop_id]),
            {
                "moisture_threshold": "10.00",
                "max_moisture": "16.00",
                "allowed_grades": ["A", "B"],
            },
            format="json",
        ).status_code
        == 200
    )
    # Append a new effective-dated price for the same grade.
    assert (
        api_client.post(
            reverse("api:price-list"),
            {
                "crop": grade.crop_id,
                "grade": "A",
                "price_per_kg": "99.00",
                "effective_from": "2026-02-01",
            },
            format="json",
        ).status_code
        == 201
    )

    after = api_client.get(reverse("api:delivery-detail", args=[snapshot["id"]])).json()
    for field in (
        "threshold_used",
        "applied_price",
        "price_list_entry",
        "deduction_kg",
        "net_kg",
        "amount",
        "crop_grade",
        "delivered_on",
    ):
        assert after[field] == snapshot[field], field
