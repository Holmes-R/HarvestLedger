"""Indian mobile format is enforced by the model and PostgreSQL schema."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from procurement.models import Farmer

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "phone",
    [
        "6000000000",
        "7000000000",
        "8000000000",
        "9876543210",
        "98765 43210",
        "+919876543210",
        "+91 9876543210",
        "+91 98765 43210",
    ],
)
def test_farmer_accepts_indian_mobile_formats(phone):
    Farmer(name="Asha", phone=phone, village="Kolar").full_clean()


@pytest.mark.parametrize(
    "phone",
    [
        "",
        "5000000000",
        "0987654321",
        "987654321",
        "98765432100",
        "+1 9876543210",
        "+91 58765 43210",
        "+91  98765 43210",
        "9876 543210",
        " 9876543210",
        "9876543210 ",
        "9876543210\n",
        "९८७६५४३२१०",
    ],
)
def test_farmer_rejects_invalid_mobile_formats(phone):
    with pytest.raises(ValidationError) as error:
        Farmer(name="Asha", phone=phone, village="Kolar").full_clean()
    assert "phone" in error.value.message_dict


@pytest.mark.parametrize("phone", ["0000000001", "9876543210\n", "+91  98765 43210"])
def test_database_rejects_invalid_mobile_when_save_bypasses_full_clean(phone):
    with pytest.raises(IntegrityError), transaction.atomic():
        Farmer.objects.create(name="Asha", phone=phone, village="Kolar")
