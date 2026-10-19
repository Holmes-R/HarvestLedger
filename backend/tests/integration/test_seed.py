"""``seed_data`` management command behaviour.

These tests assert the seed command is deterministic, idempotent,
non-destructive and atomic. It now seeds **reference data plus a
service-built financial demo** (advances, deliveries, payouts, a correction and a
supplementary payout); the reference counts are unchanged, and a second run adds
nothing, reapplies no recovery and leaves balances and snapshots untouched.
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


def test_seed_creates_expected_financial_history(seed):
    seed()
    assert Advance.objects.count() == 3
    assert Delivery.objects.filter(kind="PROCUREMENT").count() == 9
    assert Delivery.objects.exclude(kind="PROCUREMENT").count() == 1  # correction note
    assert Payout.objects.count() == 7
    assert Payout.objects.filter(status="DRAFT").count() == 2
    assert Payout.objects.filter(status="FINALISED").count() == 3
    assert Payout.objects.filter(status="PAID").count() == 2


def test_seed_does_not_persist_the_missing_rate_delivery(seed):
    seed()
    assert not Delivery.objects.filter(farmer__phone="9000000003").exists()


def test_seed_outstanding_after_recovery(seed):
    seed()
    balances = dict(Farmer.objects.values_list("phone", "outstanding_advance"))
    assert balances["9000000001"] == Decimal("0.00")  # 1000 recovery applied
    assert balances["9000000002"] == Decimal("52480.00")  # 55000 - 2x1260 carried
    assert balances["9000000003"] == Decimal("0.00")


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


def _financial_snapshot():
    return {
        "advances": list(
            Advance.objects.order_by("pk").values_list(
                "farmer__phone", "amount", "given_on"
            )
        ),
        "deliveries": list(
            Delivery.objects.order_by("pk").values_list(
                "farmer__phone", "kind", "accounting_date", "amount", "payout_id"
            )
        ),
        "payouts": list(
            Payout.objects.order_by("pk").values_list(
                "farmer__phone",
                "week_start",
                "status",
                "gross_amount",
                "advance_deduction",
                "net_amount",
            )
        ),
        "balances": list(
            Farmer.objects.order_by("phone").values_list("phone", "outstanding_advance")
        ),
    }


def test_reseeding_preserves_frozen_snapshots_and_balances(seed):
    seed()
    delivery = Delivery.objects.filter(kind="PROCUREMENT").order_by("pk").first()
    payout = Payout.objects.filter(status="PAID").order_by("pk").first()
    frozen_delivery = {
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
    frozen_payout = (
        payout.status,
        payout.gross_amount,
        payout.advance_deduction,
        payout.net_amount,
        payout.finalised_at,
        payout.paid_at,
    )

    seed()

    delivery.refresh_from_db()
    payout.refresh_from_db()
    assert {
        field: getattr(delivery, field) for field in frozen_delivery
    } == frozen_delivery
    assert (
        payout.status,
        payout.gross_amount,
        payout.advance_deduction,
        payout.net_amount,
        payout.finalised_at,
        payout.paid_at,
    ) == frozen_payout
    assert _counts() == EXPECTED


def test_two_consecutive_seed_runs_create_nothing_and_change_nothing(seed):
    seed()
    counts = _counts()
    snapshot = _financial_snapshot()

    output = seed()

    assert counts == EXPECTED
    assert _counts() == counts
    assert _financial_snapshot() == snapshot
    assert "0 created" in output


def test_seed_rolls_back_entirely_on_failure(seed, monkeypatch):
    bad = PriceSpec("MAIZE", "A", Decimal("0.00"), date(2026, 7, 1))
    monkeypatch.setattr(seed_data, "DEMO_PRICES", (*seed_data.DEMO_PRICES, bad))

    with pytest.raises(IntegrityError):
        seed()

    assert _counts() == {"crops": 0, "grades": 0, "farmers": 0, "prices": 0}
    assert Advance.objects.count() == 0
    assert Delivery.objects.count() == 0
    assert Payout.objects.count() == 0
