"""Delivery maths and recording.

* :func:`calculate_breakdown` is pure calculation -- no database, no clock. It
  turns a gross weight, moisture reading and price into a frozen breakdown.
* :func:`record_delivery` orchestrates persistence: it resolves the effective
  price, runs the calculation and writes an immutable ``PROCUREMENT`` delivery.

Moisture rule (assignment)
--------------------------
Deduction is a whole-percentage of gross weight: ``floor(moisture - threshold)``
percentage points, capped at 10%, and zero at or below the threshold. Moisture
above the crop's maximum is rejected. Money and derived weights are rounded with
``Decimal`` / ``ROUND_HALF_UP``; ``deduction_kg + net_kg == gross_weight_kg``
exactly at 5 dp.
"""

import decimal
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from procurement.models import CropGrade, Delivery, DeliveryKind, Farmer
from procurement.precision import (
    DERIVED_KG_PLACES,
    GROSS_KG_PLACES,
    MOISTURE_PLACES,
    MONEY_PLACES,
    quantize,
    validate_precision,
)

from .errors import MoistureExceedsMaximum
from .locking import lock_farmer
from .pricing import resolve_price
from .validation import as_decimal

__all__ = [
    "Breakdown",
    "MoistureExceedsMaximum",
    "calculate_breakdown",
    "record_delivery",
]

MAX_DEDUCTION_PERCENT = Decimal("10.00")
PERCENT_DIVISOR = Decimal(100)
MAX_MOISTURE_BOUND = Decimal(100)


@dataclass(frozen=True)
class Breakdown:
    """Frozen result of a delivery calculation."""

    deduction_percent: Decimal
    deduction_kg: Decimal
    net_kg: Decimal
    amount: Decimal


def _require_positive(value: Decimal, field_name: str) -> None:
    if value <= 0:
        raise ValidationError(
            f"{field_name} must be greater than zero.", code="not_positive"
        )


def calculate_breakdown(
    gross_weight_kg,
    moisture_percent,
    price_per_kg,
    threshold,
    max_moisture,
) -> Breakdown:
    """Return a :class:`Breakdown` for the given measurement and price.

    Rejects over-precise or non-positive input with ``ValidationError`` and
    rejects moisture above ``max_moisture`` with :class:`MoistureExceedsMaximum`.
    """
    gross = as_decimal(gross_weight_kg, "gross_weight_kg")
    moisture = as_decimal(moisture_percent, "moisture_percent")
    price = as_decimal(price_per_kg, "price_per_kg")
    moisture_threshold = as_decimal(threshold, "threshold")
    moisture_max = as_decimal(max_moisture, "max_moisture")

    validate_precision(gross, GROSS_KG_PLACES, "gross_weight_kg")
    validate_precision(moisture, MOISTURE_PLACES, "moisture_percent")
    validate_precision(price, MONEY_PLACES, "price_per_kg")
    validate_precision(moisture_threshold, MOISTURE_PLACES, "threshold")
    validate_precision(moisture_max, MOISTURE_PLACES, "max_moisture")

    _require_positive(gross, "gross_weight_kg")
    _require_positive(moisture, "moisture_percent")
    _require_positive(price, "price_per_kg")

    if not (Decimal(0) <= moisture_threshold <= moisture_max <= MAX_MOISTURE_BOUND):
        raise ValidationError(
            "Moisture bounds must satisfy 0 <= threshold <= max_moisture <= 100.",
            code="invalid_moisture_bounds",
        )

    if moisture > moisture_max:
        raise MoistureExceedsMaximum(
            f"moisture_percent {moisture} exceeds max_moisture {moisture_max}."
        )

    excess = moisture - moisture_threshold
    if excess <= 0:
        deduction_percent = Decimal("0.00")
    else:
        whole_percent = excess.to_integral_value(rounding=decimal.ROUND_FLOOR)
        deduction_percent = quantize(
            min(whole_percent, MAX_DEDUCTION_PERCENT), MOISTURE_PLACES
        )

    deduction_kg = quantize(
        gross * deduction_percent / PERCENT_DIVISOR, DERIVED_KG_PLACES
    )
    net_kg = quantize(gross - deduction_kg, DERIVED_KG_PLACES)
    amount = quantize(net_kg * price, MONEY_PLACES)

    return Breakdown(
        deduction_percent=deduction_percent,
        deduction_kg=deduction_kg,
        net_kg=net_kg,
        amount=amount,
    )


def record_delivery(
    *,
    farmer: Farmer,
    crop_grade: CropGrade,
    delivered_on: date,
    gross_weight_kg,
    moisture_percent,
) -> Delivery:
    """Record an immutable ``PROCUREMENT`` delivery with a frozen breakdown."""
    gross = as_decimal(gross_weight_kg, "gross_weight_kg")
    moisture = as_decimal(moisture_percent, "moisture_percent")
    if delivered_on is None:
        raise ValidationError("delivered_on is required.", code="required")

    crop = crop_grade.crop
    with transaction.atomic():
        lock_farmer(farmer.pk)
        entry = resolve_price(crop_grade, delivered_on)
        breakdown = calculate_breakdown(
            gross_weight_kg=gross,
            moisture_percent=moisture,
            price_per_kg=entry.price_per_kg,
            threshold=crop.moisture_threshold,
            max_moisture=crop.max_moisture,
        )
        return Delivery.objects.create(
            farmer=farmer,
            kind=DeliveryKind.PROCUREMENT,
            crop_grade=crop_grade,
            delivered_on=delivered_on,
            accounting_date=delivered_on,
            gross_weight_kg=gross,
            moisture_percent=moisture,
            threshold_used=crop.moisture_threshold,
            deduction_percent=breakdown.deduction_percent,
            deduction_kg=breakdown.deduction_kg,
            net_kg=breakdown.net_kg,
            applied_price=entry.price_per_kg,
            price_list_entry=entry,
            amount=breakdown.amount,
        )
