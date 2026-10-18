"""Advance posting.

Assignment rule: an advance raises the farmer's outstanding balance. The balance
is the source of truth for later recovery; posting is atomic and locks the
farmer row. Advances are keyed by their own identity -- ``(farmer, given_on)`` is
deliberately **not** unique (see ``procurement.scenarios``).
"""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction

from procurement.models import Advance, Farmer
from procurement.precision import MONEY_PLACES, validate_precision

from .locking import lock_farmer
from .money import quantize_money
from .validation import as_decimal

__all__ = ["post_advance"]


def post_advance(farmer: Farmer, amount, given_on: date) -> Advance:
    """Create an advance and increase the farmer's outstanding balance."""
    value = as_decimal(amount, "amount")
    validate_precision(value, MONEY_PLACES, "amount")
    if value <= 0:
        raise ValidationError(
            "Advance amount must be greater than zero.", code="not_positive"
        )
    if given_on is None:
        raise ValidationError("given_on is required.", code="required")

    with transaction.atomic():
        locked = lock_farmer(farmer.pk)
        advance = Advance.objects.create(
            farmer=farmer, amount=quantize_money(value), given_on=given_on
        )
        locked.outstanding_advance = quantize_money(
            locked.outstanding_advance + advance.amount
        )
        locked.save(update_fields=["outstanding_advance"])
    return advance
