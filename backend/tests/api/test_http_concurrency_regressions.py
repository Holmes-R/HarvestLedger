"""Barrier-coordinated HTTP races using independent PostgreSQL connections."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier

import pytest
from django.db import connections
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from procurement.models import Advance, Delivery, Farmer, Payout, PriceListEntry

pytestmark = [pytest.mark.m3, pytest.mark.django_db(transaction=True)]


def _price(grade):
    return PriceListEntry.objects.create(
        crop_grade=grade,
        price_per_kg=Decimal("1.00"),
        effective_from=date(2026, 1, 5),
    )


def _record(client, farmer, grade, *, day="2026-01-05", weight="100.000"):
    response = client.post(
        reverse("api:delivery-list"),
        {
            "farmer": farmer.pk,
            "crop_grade": grade.pk,
            "delivered_on": day,
            "gross_weight_kg": weight,
            "moisture_percent": "14.00",
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    return response.json()["id"]


def _advance(client, farmer, amount):
    response = client.post(
        reverse("api:advance-list"),
        {"farmer": farmer.pk, "amount": amount, "given_on": "2026-01-05"},
        format="json",
    )
    assert response.status_code == 201, response.content


def _generate(client, farmer, day="2026-01-05"):
    response = client.post(
        reverse("api:payout-generate"),
        {"farmer": farmer.pk, "week_start": day},
        format="json",
    )
    assert response.status_code == 201, response.content
    return response.json()["payout"]["id"]


def _simultaneous(*operations):
    """Start workers together, bound their waits, and surface every exception."""
    barrier = Barrier(len(operations))

    def worker(operation):
        try:
            barrier.wait(timeout=10)
            return operation(APIClient())
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        futures = [pool.submit(worker, operation) for operation in operations]
        return [future.result(timeout=20) for future in futures]


def test_same_week_generation_and_same_payout_finalisation_races(farmer, grade):
    _price(grade)
    client = APIClient()
    _advance(client, farmer, "100.00")
    delivery_id = _record(client, farmer, grade, weight="100.050")

    def generate(other):
        return other.post(
            reverse("api:payout-generate"),
            {"farmer": farmer.pk, "week_start": "2026-01-05"},
            format="json",
        )

    responses = _simultaneous(generate, generate)
    assert sorted(response.status_code for response in responses) == [201, 201]
    payout_ids = [response.json()["payout"]["id"] for response in responses]
    assert payout_ids[0] == payout_ids[1]
    assert Payout.objects.filter(farmer=farmer).count() == 1
    assert Delivery.objects.get(pk=delivery_id).payout_id == payout_ids[0]
    assert Farmer.objects.get(pk=farmer.pk).outstanding_advance == Decimal("100.00")

    def finalise(other):
        return other.post(reverse("api:payout-finalise", args=[payout_ids[0]]))

    responses = _simultaneous(finalise, finalise)
    assert sorted(response.status_code for response in responses) == [200, 409]
    payout = Payout.objects.get(pk=payout_ids[0])
    assert payout.status == "FINALISED"
    assert (payout.gross_amount, payout.advance_deduction, payout.net_amount) == (
        Decimal("100.05"),
        Decimal("30.01"),
        Decimal("70.04"),
    )
    assert Farmer.objects.get(pk=farmer.pk).outstanding_advance == Decimal("69.99")


def test_different_week_finalisations_share_one_balance(farmer, grade):
    _price(grade)
    client = APIClient()
    _advance(client, farmer, "50.00")
    payout_ids = []
    delivery_ids = []
    for day in ("2026-01-05", "2026-01-12"):
        delivery_ids.append(_record(client, farmer, grade, day=day))
        payout_ids.append(_generate(client, farmer, day))

    responses = _simultaneous(
        *(
            lambda other, pk=pk: other.post(reverse("api:payout-finalise", args=[pk]))
            for pk in payout_ids
        )
    )
    assert [response.status_code for response in responses] == [200, 200]
    payouts = list(Payout.objects.filter(pk__in=payout_ids))
    assert all(payout.status == "FINALISED" for payout in payouts)
    assert all(payout.gross_amount == Decimal("100.00") for payout in payouts)
    assert sum((p.advance_deduction for p in payouts), Decimal("0.00")) == Decimal(
        "50.00"
    )
    assert Farmer.objects.get(pk=farmer.pk).outstanding_advance == Decimal("0.00")
    assert {d.payout_id for d in Delivery.objects.filter(pk__in=delivery_ids)} == set(
        payout_ids
    )


def test_advance_creation_and_finalisation_serialize(farmer, grade):
    _price(grade)
    client = APIClient()
    _advance(client, farmer, "20.00")
    delivery_id = _record(client, farmer, grade)
    payout_id = _generate(client, farmer)

    responses = _simultaneous(
        lambda other: other.post(
            reverse("api:advance-list"),
            {"farmer": farmer.pk, "amount": "50.00", "given_on": "2026-01-05"},
            format="json",
        ),
        lambda other: other.post(reverse("api:payout-finalise", args=[payout_id])),
    )
    assert [response.status_code for response in responses] == [201, 200]
    payout = Payout.objects.get(pk=payout_id)
    balance = Farmer.objects.get(pk=farmer.pk).outstanding_advance
    assert (payout.advance_deduction, balance) in {
        (Decimal("20.00"), Decimal("50.00")),
        (Decimal("30.00"), Decimal("40.00")),
    }
    assert payout.gross_amount == Decimal("100.00")
    assert payout.net_amount == payout.gross_amount - payout.advance_deduction
    assert Delivery.objects.get(pk=delivery_id).payout_id == payout_id
    assert Advance.objects.filter(farmer=farmer).count() == 2


def test_delivery_edit_and_finalisation_serialize(farmer, grade):
    _price(grade)
    client = APIClient()
    delivery_id = _record(client, farmer, grade)
    payout_id = _generate(client, farmer)

    responses = _simultaneous(
        lambda other: other.patch(
            reverse("api:delivery-detail", args=[delivery_id]),
            {"gross_weight_kg": "120.000"},
            format="json",
        ),
        lambda other: other.post(reverse("api:payout-finalise", args=[payout_id])),
    )
    assert responses[1].status_code == 200
    assert responses[0].status_code in (200, 409)
    delivery = Delivery.objects.get(pk=delivery_id)
    payout = Payout.objects.get(pk=payout_id)
    assert payout.status == "FINALISED"
    assert delivery.payout_id == payout_id
    if responses[0].status_code == 200:
        assert delivery.amount == payout.gross_amount == Decimal("120.00")
    else:
        assert delivery.amount == payout.gross_amount == Decimal("100.00")
    assert payout.net_amount == payout.gross_amount
    assert Farmer.objects.get(pk=farmer.pk).outstanding_advance == Decimal("0.00")


@override_settings(ALLOW_REVIEW_CLOCK=True, REVIEW_CLOCK_KEY="probe-key")
def test_simultaneous_http_reviewer_clocks_are_request_local(farmer, grade):
    _price(grade)

    def preview_at(instant):
        return lambda other: other.post(
            reverse("api:delivery-preview"),
            {
                "farmer": farmer.pk,
                "crop_grade": grade.pk,
                "delivered_on": "2026-01-05",
                "gross_weight_kg": "100.000",
                "moisture_percent": "14.00",
            },
            format="json",
            HTTP_X_TEST_CLOCK=instant,
            HTTP_X_REVIEW_KEY="probe-key",
        )

    responses = _simultaneous(
        preview_at("2026-01-05T00:15:00+05:30"),
        preview_at("2026-01-06T00:15:00+05:30"),
    )
    assert [response.status_code for response in responses] == [200, 200]
    assert [response.json()["business_date"] for response in responses] == [
        "2026-01-05",
        "2026-01-06",
    ]
    assert Delivery.objects.count() == 0
