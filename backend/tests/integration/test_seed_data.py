"""seed_data must be idempotent and must not create financial records."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from procurement.management.commands import seed_data as sd
from procurement.models import (
    Advance,
    Crop,
    CropGrade,
    Delivery,
    Farmer,
    Payout,
    PriceListEntry,
)


def _reference_counts() -> tuple[int, int, int, int]:
    return (
        Crop.objects.count(),
        CropGrade.objects.count(),
        Farmer.objects.count(),
        PriceListEntry.objects.count(),
    )


@pytest.mark.django_db
def test_seed_is_idempotent_and_creates_no_financial_records():
    call_command("seed_data", stdout=StringIO())
    first = _reference_counts()

    second_run = StringIO()
    call_command("seed_data", stdout=second_run)
    second = _reference_counts()

    assert first == second
    assert " 0 created" in second_run.getvalue() or "0 created" in second_run.getvalue()

    expected_grades = sum(len(crop.grades) for crop in sd.DEMO_CROPS)
    assert first == (
        len(sd.DEMO_CROPS),
        expected_grades,
        len(sd.DEMO_FARMERS),
        len(sd.DEMO_PRICES),
    )

    assert Advance.objects.count() == 0
    assert Delivery.objects.count() == 0
    assert Payout.objects.count() == 0
    balances = set(Farmer.objects.values_list("outstanding_advance", flat=True))
    assert balances == {Decimal(0)}
