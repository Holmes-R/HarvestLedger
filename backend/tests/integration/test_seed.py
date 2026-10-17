"""``seed_data`` management command behaviour.

All tests here are M1 and must pass: they assert the seed command is
deterministic, idempotent, non-destructive and atomic, and that it creates
reference data only (never financial rows).
"""

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import IntegrityError

from procurement.management.commands import seed_data
from procurement.management.commands.seed_data import PriceSpec
from procurement.models import (
    Advance,
    Crop,
    CropGrade,
    Delivery,
    Farmer,
    Payout,
    PriceListEntry,
)


@pytest.fixture
def seed(db):
    def _run():
        out = StringIO()
        call_command("seed_data", stdout=out)
        return out.getvalue()

    return _run


def _counts():
    return {
        "crops": Crop.objects.count(),
        "grades": CropGrade.objects.count(),
        "farmers": Farmer.objects.count(),
        "prices": PriceListEntry.objects.count(),
    }


EXPECTED = {"crops": 3, "grades": 5, "farmers": 3, "prices": 10}


def test_seed_populates_expected_reference_data(seed):
    seed()
    assert _counts() == EXPECTED


def test_seed_creates_no_financial_records(seed):
    seed()
    assert Advance.objects.count() == 0
    assert Delivery.objects.count() == 0
    assert Payout.objects.count() == 0


def test_seed_farmers_have_zero_outstanding(seed):
    seed()
    assert set(Farmer.objects.values_list("outstanding_advance", flat=True)) == {
        Decimal("0.00")
    }


def test_seed_is_idempotent(seed):
    seed()
    output = seed()
    assert _counts() == EXPECTED
    assert "0 created" in output


def test_seed_preserves_existing_values(seed):
    seed()

    farmer = Farmer.objects.get(phone="0000000001")
    farmer.outstanding_advance = Decimal("250.00")
    farmer.save()

    entry = PriceListEntry.objects.get(
        crop_grade__crop__name="Maize",
        crop_grade__code="A",
        effective_from=date(2026, 1, 1),
    )
    entry.price_per_kg = Decimal("99.99")
    entry.save()

    seed()

    farmer.refresh_from_db()
    entry.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("250.00")
    assert entry.price_per_kg == Decimal("99.99")
    assert _counts() == EXPECTED


def test_seed_rolls_back_entirely_on_failure(seed, monkeypatch):
    bad = PriceSpec("MAIZE", "A", Decimal("0.00"), date(2026, 7, 1))
    monkeypatch.setattr(seed_data, "DEMO_PRICES", (*seed_data.DEMO_PRICES, bad))

    with pytest.raises(IntegrityError):
        seed()

    assert _counts() == {"crops": 0, "grades": 0, "farmers": 0, "prices": 0}
    assert Advance.objects.count() == 0
    assert Delivery.objects.count() == 0
    assert Payout.objects.count() == 0
