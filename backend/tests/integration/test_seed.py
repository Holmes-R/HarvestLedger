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
    first_counts = _counts()
    output = seed()
    assert first_counts == EXPECTED
    assert _counts() == first_counts
    assert "0 created" in output


def test_seed_preserves_existing_values(seed):
    seed()

    farmer = Farmer.objects.get(phone="9000000001")
    farmer.outstanding_advance = Decimal("250.00")
    farmer.save()

    entry = PriceListEntry.objects.get(
        crop_grade__crop__name="Maize",
        crop_grade__code="A",
        effective_from=date(2026, 1, 1),
    )
    entry.price_per_kg = Decimal("99.99")
    entry.save()
    price_history = list(
        PriceListEntry.objects.order_by("crop_grade_id", "effective_from").values_list(
            "crop_grade_id", "effective_from", "price_per_kg"
        )
    )

    seed()

    farmer.refresh_from_db()
    entry.refresh_from_db()
    assert farmer.outstanding_advance == Decimal("250.00")
    assert entry.price_per_kg == Decimal("99.99")
    assert (
        list(
            PriceListEntry.objects.order_by(
                "crop_grade_id", "effective_from"
            ).values_list("crop_grade_id", "effective_from", "price_per_kg")
        )
        == price_history
    )
    assert _counts() == EXPECTED


def test_reseeding_preserves_frozen_delivery_and_financial_rows(seed):
    seed()
    farmer = Farmer.objects.get(phone="9000000001")
    entry = PriceListEntry.objects.get(
        crop_grade__crop__name="Maize",
        crop_grade__code="A",
        effective_from=date(2026, 1, 1),
    )
    payout = Payout.objects.create(
        farmer=farmer,
        week_start=date(2026, 1, 5),
        week_end=date(2026, 1, 11),
        gross_amount=Decimal("2450.00"),
        net_amount=Decimal("2450.00"),
    )
    delivery = Delivery.objects.create(
        farmer=farmer,
        crop_grade=entry.crop_grade,
        delivered_on=date(2026, 1, 6),
        accounting_date=date(2026, 1, 6),
        gross_weight_kg=Decimal("100.000"),
        moisture_percent=Decimal("14.00"),
        threshold_used=Decimal("14.00"),
        deduction_percent=Decimal("0.00"),
        deduction_kg=Decimal("0.00000"),
        net_kg=Decimal("100.00000"),
        applied_price=entry.price_per_kg,
        price_list_entry=entry,
        amount=Decimal("2450.00"),
        payout=payout,
    )
    frozen = {
        field: getattr(delivery, field)
        for field in (
            "farmer_id",
            "payout_id",
            "price_list_entry_id",
            "gross_weight_kg",
            "moisture_percent",
            "threshold_used",
            "deduction_percent",
            "deduction_kg",
            "net_kg",
            "applied_price",
            "amount",
            "calculation_version",
        )
    }

    seed()

    delivery.refresh_from_db()
    payout.refresh_from_db()
    assert {field: getattr(delivery, field) for field in frozen} == frozen
    assert (payout.gross_amount, payout.net_amount) == (
        Decimal("2450.00"),
        Decimal("2450.00"),
    )
    assert (
        Advance.objects.count(),
        Delivery.objects.count(),
        Payout.objects.count(),
    ) == (
        0,
        1,
        1,
    )
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
