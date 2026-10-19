"""M3: gated reviewer business-clock aid (X-Test-Clock / X-Review-Key).

Covers README section 10: the aid is off by default, requires a shared secret,
accepts only a timezone-aware ISO-8601 instant, is request-local (two concurrent
requests with different clocks each see their own business date) and never moves
the real audit clock or request log time.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from procurement.api.middleware import ReviewClockMiddleware
from procurement.clock import get_clock
from procurement.models import Delivery

pytestmark = pytest.mark.m3

DAY = "2026-01-05"  # Monday; price effective 2026-01-01
PAYLOAD = {
    "delivered_on": DAY,
    "gross_weight_kg": "100.000",
    "moisture_percent": "14.00",
}

KEY = "demo-review-key-123"

#: A frozen instant whose IST business date is distinctive and far from "today".
FROZEN = "2026-12-31T23:00:00+05:30"
FROZEN_DATE = "2026-12-31"


def _error(response):
    return response.json()["error"]


def _preview(api_client, farmer, grade, clock=None, key=None):
    headers = {}
    if clock is not None:
        headers["HTTP_X_TEST_CLOCK"] = clock
    if key is not None:
        headers["HTTP_X_REVIEW_KEY"] = key
    return api_client.post(
        reverse("api:delivery-preview"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
        **headers,
    )


@pytest.mark.django_db
@override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY=KEY)
def test_no_header_uses_the_real_clock(api_client, farmer, grade, price):
    response = _preview(api_client, farmer, grade)
    assert response.status_code == 200
    assert response.json()["business_date"] == get_clock().today().isoformat()


@pytest.mark.django_db
@override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY=KEY)
def test_authorised_override_sets_the_business_date(api_client, farmer, grade, price):
    response = _preview(api_client, farmer, grade, clock=FROZEN, key=KEY)
    assert response.status_code == 200
    body = response.json()
    assert body["business_date"] == FROZEN_DATE
    # The override changes only business dates; the snapshot date is unchanged.
    assert body["accounting_date"] == DAY


@pytest.mark.django_db
@override_settings(ALLOW_REVIEW_CLOCK=False, REVIEW_CLOCK_KEY=KEY)
def test_disabled_flag_rejects_override(api_client, farmer, grade, price):
    response = _preview(api_client, farmer, grade, clock=FROZEN, key=KEY)
    assert response.status_code == 403
    error = _error(response)
    assert error["code"] == "review_clock_disabled"
    assert error["details"] == {}
    assert error["request_id"]
    assert response["X-Request-ID"] == error["request_id"]


@pytest.mark.django_db
@override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY=KEY)
def test_missing_key_is_unauthorised(api_client, farmer, grade, price):
    response = _preview(api_client, farmer, grade, clock=FROZEN)
    assert response.status_code == 403
    assert _error(response)["code"] == "review_clock_unauthorized"


@pytest.mark.django_db
@override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY=KEY)
def test_wrong_key_is_unauthorised(api_client, farmer, grade, price):
    response = _preview(api_client, farmer, grade, clock=FROZEN, key="nope")
    assert response.status_code == 403
    assert _error(response)["code"] == "review_clock_unauthorized"


@override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY=KEY)
def test_non_ascii_key_is_rejected_not_crashing():
    request = RequestFactory().get(
        "/api/v1/deliveries/preview/",
        HTTP_X_TEST_CLOCK=FROZEN,
        HTTP_X_REVIEW_KEY="cl\u00e9",
    )
    response = ReviewClockMiddleware(lambda _request: HttpResponse("ok"))(request)
    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY=KEY)
def test_malformed_timestamp_is_rejected(api_client, farmer, grade, price):
    response = _preview(api_client, farmer, grade, clock="not-a-timestamp", key=KEY)
    assert response.status_code == 400
    assert _error(response)["code"] == "review_clock_invalid"


@pytest.mark.django_db
@override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY=KEY)
def test_timezone_naive_timestamp_is_rejected(api_client, farmer, grade, price):
    response = _preview(
        api_client, farmer, grade, clock="2026-03-16T00:30:00", key=KEY
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "review_clock_invalid"


@pytest.mark.django_db
@override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY=KEY)
def test_audit_timestamp_stays_on_real_time(api_client, farmer, grade, price):
    response = api_client.post(
        reverse("api:delivery-list"),
        {**PAYLOAD, "farmer": farmer.id, "crop_grade": grade.id},
        format="json",
        HTTP_X_TEST_CLOCK=FROZEN,
        HTTP_X_REVIEW_KEY=KEY,
    )
    assert response.status_code == 201
    delivery = Delivery.objects.get(pk=response.json()["id"])
    # ``recorded_at`` is a real aware instant, not the frozen reviewer instant.
    assert delivery.recorded_at != datetime.fromisoformat(FROZEN)
    assert abs(delivery.recorded_at - timezone.now()) < timedelta(minutes=1)


@override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY=KEY)
def test_concurrent_requests_keep_independent_business_dates():
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
            HTTP_X_REVIEW_KEY=KEY,
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
    # No leakage: the default request context still sees real time.
    assert get_clock().today().isoformat() == real_today


@pytest.mark.django_db
@override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY=KEY)
def test_review_key_is_never_logged(api_client, farmer, grade, price, caplog):
    caplog.set_level("WARNING", logger="procurement.api")
    _preview(api_client, farmer, grade, clock=FROZEN, key="super-secret-value")
    assert "super-secret-value" not in caplog.text
    assert FROZEN not in caplog.text
