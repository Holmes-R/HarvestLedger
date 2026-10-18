"""Shared fixtures for the M3 API tests (isolated PostgreSQL test database)."""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from procurement.models import Crop, CropGrade, Farmer, PriceListEntry


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def crop(db):
    return Crop.objects.create(
        name="Maize",
        moisture_threshold=Decimal("14.00"),
        max_moisture=Decimal("20.00"),
    )


@pytest.fixture
def grade(db, crop):
    return CropGrade.objects.create(crop=crop, code="A")


@pytest.fixture
def farmer(db):
    return Farmer.objects.create(name="Asha", phone="9000000001", village="Kolar")


@pytest.fixture
def other_farmer(db):
    return Farmer.objects.create(name="Bala", phone="9000000002", village="Tumkur")


@pytest.fixture
def price(db, grade):
    return PriceListEntry.objects.create(
        crop_grade=grade,
        price_per_kg=Decimal("24.50"),
        effective_from=date(2026, 1, 1),
    )
