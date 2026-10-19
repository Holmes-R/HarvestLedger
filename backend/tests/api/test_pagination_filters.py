"""M3: bounded pagination, whitelisted ordering and list filters."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from procurement.clock import FrozenClock
from procurement.models import Crop, CropGrade, Farmer, Payout
from procurement.services import delivery

pytestmark = pytest.mark.m3

MON = date(2026, 1, 5)
TUE = date(2026, 1, 6)


def _error(response):
    return response.json()["error"]


def _clock(day):
    return FrozenClock(datetime(day.year, day.month, day.day, 6, tzinfo=UTC))


def _record(farmer, grade, day, weight="10.000"):
    return delivery.record_delivery(
        farmer=farmer,
        crop_grade=grade,
        delivered_on=day,
        gross_weight_kg=Decimal(weight),
        moisture_percent=Decimal("14.00"),
        clock=_clock(day),
    )


# --- Pagination boundaries --------------------------------------------------


@pytest.mark.django_db
def test_default_page_size_is_twenty(api_client):
    Farmer.objects.bulk_create(
        Farmer(name=f"Farmer {index}", phone=f"9{index:09d}", village="Kolar")
        for index in range(45)
    )
    response = api_client.get(reverse("api:farmer-list"))
    body = response.json()
    assert response.status_code == 200
    assert body["count"] == 45
    assert len(body["results"]) == 20
    assert body["next"] is not None and body["previous"] is None


@pytest.mark.django_db
def test_page_size_is_bounded_at_one_hundred(api_client):
    Farmer.objects.bulk_create(
        Farmer(name=f"Farmer {index}", phone=f"9{index:09d}", village="Kolar")
        for index in range(105)
    )
    url = reverse("api:farmer-list")

    small = api_client.get(url, {"page_size": 5}).json()
    assert len(small["results"]) == 5

    # A too-large request is clamped to the maximum, never honoured.
    capped = api_client.get(url, {"page_size": 1000}).json()
    assert len(capped["results"]) == 100
    assert capped["count"] == 105
    assert capped["next"] is not None


@pytest.mark.django_db
def test_pagination_walks_every_page_once(api_client, farmer, grade, price):
    for index in range(25):
        _record(farmer, grade, MON, weight=f"{index + 1}.000")

    url = reverse("api:delivery-list")
    seen = []
    page = 1
    while True:
        body = api_client.get(url, {"page": page, "page_size": 10}).json()
        seen.extend(row["id"] for row in body["results"])
        if body["next"] is None:
            break
        page += 1

    assert page == 3
    assert len(seen) == 25
    assert len(set(seen)) == 25  # no record repeated across pages
    assert seen == sorted(seen, reverse=True)  # newest accounting_date, then id desc


@pytest.mark.django_db
def test_page_out_of_range_is_not_found(api_client, farmer, grade, price):
    _record(farmer, grade, MON)
    response = api_client.get(reverse("api:delivery-list"), {"page": 999})
    assert response.status_code == 404
    assert _error(response)["code"] == "not_found"


# --- Malformed filters ------------------------------------------------------


@pytest.mark.django_db
def test_malformed_filter_types_are_rejected(api_client, farmer, grade, price):
    cases = [
        ("api:delivery-list", {"farmer": "abc"}, "farmer"),
        ("api:delivery-list", {"from": "not-a-date"}, "from"),
        ("api:advance-list", {"farmer": "1.5"}, "farmer"),
        ("api:advance-list", {"to": "2026-13-01"}, "to"),
        ("api:payout-list", {"farmer": "x"}, "farmer"),
        ("api:payout-list", {"week": "nope"}, "week"),
        ("api:payout-list", {"status": "NOPE"}, "status"),
        ("api:price-list", {"crop": "abc"}, "crop"),
        ("api:correction-list", {"original_delivery": "abc"}, "original_delivery"),
    ]
    for name, params, field in cases:
        response = api_client.get(reverse(name), params)
        assert response.status_code == 400, (name, params)
        assert _error(response)["code"] == "invalid", (name, params)
        assert field in _error(response)["details"], (name, params)


@pytest.mark.django_db
def test_reversed_date_ranges_are_rejected(api_client, farmer, grade, price):
    params = {"from": "2026-02-01", "to": "2026-01-01"}
    for name in (
        "api:delivery-list",
        "api:advance-list",
        "api:payout-list",
        "api:correction-list",
    ):
        response = api_client.get(reverse(name), params)
        assert response.status_code == 400, name
        assert _error(response)["code"] == "invalid", name

    ledger = api_client.get(reverse("api:farmer-ledger", args=[farmer.id]), params)
    assert ledger.status_code == 400
    assert _error(ledger)["code"] == "invalid"


@pytest.mark.django_db
def test_unknown_ordering_field_is_rejected(api_client, farmer):
    response = api_client.get(
        reverse("api:farmer-list"), {"ordering": "password"}
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "invalid"
    assert "ordering" in _error(response)["details"]


# --- Deterministic ordering (id tie-breaker) --------------------------------


@pytest.mark.django_db
def test_default_ordering_is_deterministic_with_id_tie_breaker(
    api_client, farmer, grade, price
):
    ids = [_record(farmer, grade, MON).id for _ in range(3)]
    url = reverse("api:delivery-list")

    default = api_client.get(url).json()
    assert [row["id"] for row in default["results"]] == sorted(ids, reverse=True)

    again = api_client.get(url).json()
    assert again["results"] == default["results"]  # stable across calls

    ascending = api_client.get(url, {"ordering": "accounting_date"}).json()
    assert [row["id"] for row in ascending["results"]] == sorted(ids)


@pytest.mark.django_db
def test_ordering_can_be_reversed(api_client, db):
    Farmer.objects.bulk_create(
        Farmer(name=name, phone=phone, village="Kolar")
        for name, phone in [("Zara", "9000000001"), ("Asha", "9000000002")]
    )
    body = api_client.get(
        reverse("api:farmer-list"), {"ordering": "-name"}
    ).json()
    assert [row["name"] for row in body["results"]] == ["Zara", "Asha"]


# --- Inclusive date filters and combined filters ----------------------------


@pytest.mark.django_db
def test_delivery_date_filters_are_inclusive(api_client, farmer, grade, price):
    _record(farmer, grade, MON)
    _record(farmer, grade, TUE)
    url = reverse("api:delivery-list")

    same_day = api_client.get(url, {"from": "2026-01-05", "to": "2026-01-05"}).json()
    assert same_day["count"] == 1
    assert same_day["results"][0]["accounting_date"] == "2026-01-05"

    span = api_client.get(url, {"from": "2026-01-05", "to": "2026-01-06"}).json()
    assert span["count"] == 2


@pytest.mark.django_db
def test_advance_date_range_filter(api_client, farmer, grade, price):
    from procurement.services import advances

    advances.post_advance(farmer, Decimal("100.00"), MON)
    advances.post_advance(farmer, Decimal("200.00"), date(2026, 2, 10))
    url = reverse("api:advance-list")

    january = api_client.get(
        url, {"farmer": farmer.id, "from": "2026-01-01", "to": "2026-01-31"}
    ).json()
    assert january["count"] == 1
    assert january["results"][0]["amount"] == "100.00"


@pytest.mark.django_db
def test_delivery_combined_filters(api_client, farmer, other_farmer, grade, price):
    _record(farmer, grade, MON)
    _record(other_farmer, grade, MON)
    url = reverse("api:delivery-list")

    combined = api_client.get(
        url,
        {
            "farmer": farmer.id,
            "kind": "PROCUREMENT",
            "from": "2026-01-01",
            "to": "2026-01-31",
        },
    ).json()
    assert combined["count"] == 1

    # A far window excludes everything without changing the filter semantics.
    empty = api_client.get(
        url, {"farmer": farmer.id, "from": "2027-01-01", "to": "2027-12-31"}
    ).json()
    assert empty["count"] == 0


@pytest.mark.django_db
def test_payout_week_and_status_filters(api_client, farmer):
    Payout.objects.create(farmer=farmer, week_start=MON, week_end=date(2026, 1, 11))
    url = reverse("api:payout-list")

    # A mid-week day is normalised to the Monday, so the payout is found.
    by_week = api_client.get(url, {"week": "2026-01-07"}).json()
    assert by_week["count"] == 1
    assert by_week["results"][0]["week_start"] == "2026-01-05"

    by_status = api_client.get(url, {"status": "DRAFT", "farmer": farmer.id}).json()
    assert by_status["count"] == 1

    other_week = api_client.get(url, {"week": "2026-01-12"}).json()
    assert other_week["count"] == 0


@pytest.mark.django_db
def test_price_filters_by_crop_and_grade(api_client, crop, grade, price):
    other = Crop.objects.create(
        name="Groundnut", moisture_threshold=Decimal("12.00"), max_moisture=Decimal("18.00")
    )
    other_grade = CropGrade.objects.create(crop=other, code="A")
    url = reverse("api:price-list")

    by_grade = api_client.get(url, {"crop_grade": grade.id}).json()
    assert by_grade["count"] == 1
    assert by_grade["results"][0]["crop_grade"] == grade.id

    by_crop = api_client.get(url, {"crop": crop.id}).json()
    assert by_crop["count"] == 1

    no_match = api_client.get(url, {"crop": other.id}).json()
    assert no_match["count"] == 0
    assert other_grade.id != grade.id
