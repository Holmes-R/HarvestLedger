"""Delivery maths, previewing, recording and editing.

* :func:`calculate_breakdown` is pure calculation -- no database, no clock. It
  turns a gross weight, moisture reading and price into a frozen breakdown.
* :func:`preview_delivery` validates the input, resolves the effective price and
  returns the full calculated breakdown **without writing anything**.
* :func:`record_delivery` re-validates and re-calculates authoritatively (it
  never trusts a preview or any client-supplied breakdown) and writes an
  immutable ``PROCUREMENT`` delivery inside a transaction under the farmer lock.
* :func:`edit_delivery` recalculates an existing delivery while it is not part
  of a settled payout, refreshing any DRAFT payout so its totals cannot go stale.

Moisture rule (assignment)
--------------------------
Deduction is a whole-percentage of gross weight: ``floor(moisture - threshold)``
percentage points, capped at 10%, and zero at or below the threshold. Moisture
above the crop's maximum is rejected. Money and derived weights are rounded with
``Decimal`` / ``ROUND_HALF_UP``; ``deduction_kg + net_kg == gross_weight_kg``
exactly at 5 dp.

Dates
-----
``delivered_on`` is an IST business date and may not be in the future relative to
the injected business clock (``clock`` / :func:`procurement.clock.get_clock`).
For an ordinary ``PROCUREMENT`` delivery ``accounting_date == delivered_on``.

Editing policy
--------------
* A delivery in a FINALISED or PAID payout is immutable -- :func:`edit_delivery`
  raises :class:`~procurement.services.errors.PayoutStateError`.
* Editing recalculates the snapshot from the (possibly new) measurements.
* The frozen price is **preserved** unless the pricing basis changes: the price
  is re-resolved only when ``crop_grade`` or ``delivered_on`` is edited, so adding
  a new price entry never rewrites an existing delivery's ``applied_price``.
* When the delivery belongs to a DRAFT payout the draft is refreshed; if the edit
  moves it to a different Monday..Sunday week it is detached from the old draft
  and attached to the DRAFT for the new week (created if needed). Empty drafts
  left behind are removed, so DRAFT totals never silently go stale.
"""

import decimal
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from procurement.clock import Clock, get_clock, week_start
from procurement.models import (
    CropGrade,
    Delivery,
    DeliveryKind,
    Farmer,
    Payout,
    PayoutStatus,
    PriceListEntry,
)
from procurement.precision import (
    DERIVED_KG_PLACES,
    GROSS_KG_PLACES,
    MOISTURE_PLACES,
    MONEY_PLACES,
    quantize,
    validate_precision,
)

from .errors import MoistureExceedsMaximum, PayoutStateError
from .locking import lock_farmer, lock_payout
from .money import quantize_money
from .pricing import resolve_price
from .validation import as_decimal

__all__ = [
    "Breakdown",
    "DeliveryPreview",
    "MoistureExceedsMaximum",
    "calculate_breakdown",
    "edit_delivery",
    "preview_delivery",
    "record_delivery",
]

MAX_DEDUCTION_PERCENT = Decimal("10.00")
PERCENT_DIVISOR = Decimal(100)
MAX_MOISTURE_BOUND = Decimal(100)
WEEK_LENGTH_DAYS = 6
ZERO = Decimal("0.00")
_SETTLED_STATUSES = (PayoutStatus.FINALISED, PayoutStatus.PAID)


@dataclass(frozen=True)
class Breakdown:
    """Frozen result of a delivery calculation."""

    deduction_percent: Decimal
    deduction_kg: Decimal
    net_kg: Decimal
    amount: Decimal


@dataclass(frozen=True)
class DeliveryPreview:
    """Full, non-persisted result of pricing and calculating a delivery."""

    farmer_id: int
    crop_grade: CropGrade
    delivered_on: date
    accounting_date: date
    gross_weight_kg: Decimal
    moisture_percent: Decimal
    threshold_used: Decimal
    applied_price: Decimal
    price_list_entry: PriceListEntry
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


def _validate_delivered_on(delivered_on: date, today: date) -> None:
    if delivered_on is None:
        raise ValidationError("delivered_on is required.", code="required")
    if isinstance(delivered_on, datetime) or not isinstance(delivered_on, date):
        raise ValidationError(
            "delivered_on must be a calendar date.", code="invalid_date"
        )
    if delivered_on > today:
        raise ValidationError(
            f"delivered_on {delivered_on} is in the future "
            f"(business date {today}).",
            code="future_delivery_date",
        )


def _build_preview(
    *,
    farmer: Farmer,
    crop_grade: CropGrade,
    delivered_on: date,
    gross_weight_kg,
    moisture_percent,
    clock: Clock | None,
    price_entry: PriceListEntry | None = None,
) -> DeliveryPreview:
    """Validate inputs, resolve the price and calculate the full breakdown.

    Read-only: performs no writes. Shared by :func:`preview_delivery` and
    :func:`record_delivery`, so a preview and the record it precedes always agree.
    """
    if farmer is None or getattr(farmer, "pk", None) is None:
        raise ValidationError("A saved farmer is required.", code="farmer_required")
    if crop_grade is None or getattr(crop_grade, "pk", None) is None:
        raise ValidationError(
            "A saved crop grade is required.", code="crop_grade_required"
        )

    today = (clock or get_clock()).today()
    _validate_delivered_on(delivered_on, today)

    gross = as_decimal(gross_weight_kg, "gross_weight_kg")
    moisture = as_decimal(moisture_percent, "moisture_percent")

    crop = crop_grade.crop
    entry = price_entry if price_entry is not None else resolve_price(
        crop_grade, delivered_on
    )
    breakdown = calculate_breakdown(
        gross_weight_kg=gross,
        moisture_percent=moisture,
        price_per_kg=entry.price_per_kg,
        threshold=crop.moisture_threshold,
        max_moisture=crop.max_moisture,
    )

    return DeliveryPreview(
        farmer_id=farmer.pk,
        crop_grade=crop_grade,
        delivered_on=delivered_on,
        accounting_date=delivered_on,
        gross_weight_kg=gross,
        moisture_percent=moisture,
        threshold_used=crop.moisture_threshold,
        applied_price=entry.price_per_kg,
        price_list_entry=entry,
        deduction_percent=breakdown.deduction_percent,
        deduction_kg=breakdown.deduction_kg,
        net_kg=breakdown.net_kg,
        amount=breakdown.amount,
    )


def preview_delivery(
    *,
    farmer: Farmer,
    crop_grade: CropGrade,
    delivered_on: date,
    gross_weight_kg,
    moisture_percent,
    clock: Clock | None = None,
) -> DeliveryPreview:
    """Return the full calculated breakdown for a delivery, writing nothing."""
    return _build_preview(
        farmer=farmer,
        crop_grade=crop_grade,
        delivered_on=delivered_on,
        gross_weight_kg=gross_weight_kg,
        moisture_percent=moisture_percent,
        clock=clock,
    )


def record_delivery(
    *,
    farmer: Farmer,
    crop_grade: CropGrade,
    delivered_on: date,
    gross_weight_kg,
    moisture_percent,
    clock: Clock | None = None,
) -> Delivery:
    """Record an immutable ``PROCUREMENT`` delivery with a frozen breakdown.

    Validation and calculation are repeated here authoritatively -- no
    client-supplied breakdown or earlier preview is trusted.
    """
    # Authoritative: recalculate from the raw measurements, inside the lock.
    with transaction.atomic():
        lock_farmer(farmer.pk)
        preview = _build_preview(
            farmer=farmer,
            crop_grade=crop_grade,
            delivered_on=delivered_on,
            gross_weight_kg=gross_weight_kg,
            moisture_percent=moisture_percent,
            clock=clock,
        )
        return Delivery.objects.create(
            farmer=farmer,
            kind=DeliveryKind.PROCUREMENT,
            crop_grade=preview.crop_grade,
            delivered_on=preview.delivered_on,
            accounting_date=preview.accounting_date,
            gross_weight_kg=preview.gross_weight_kg,
            moisture_percent=preview.moisture_percent,
            threshold_used=preview.threshold_used,
            deduction_percent=preview.deduction_percent,
            deduction_kg=preview.deduction_kg,
            net_kg=preview.net_kg,
            applied_price=preview.applied_price,
            price_list_entry=preview.price_list_entry,
            amount=preview.amount,
        )


def _refresh_draft(payout: Payout) -> None:
    """Recompute a DRAFT payout's totals from its current deliveries."""
    gross = quantize_money(sum((d.amount for d in payout.deliveries.all()), ZERO))
    payout.gross_amount = gross
    # A draft never reduces the balance; net tracks gross until finalised.
    payout.net_amount = gross
    payout.save(update_fields=["gross_amount", "net_amount"])


def _reconcile_draft(delivery: Delivery, draft: Payout, farmer: Farmer) -> None:
    """Keep the delivery's DRAFT payout consistent after an edit."""
    target_start = week_start(delivery.accounting_date)
    if target_start == draft.week_start:
        _refresh_draft(draft)
        return

    target = (
        Payout.objects.filter(
            farmer=farmer, week_start=target_start, status=PayoutStatus.DRAFT
        )
        .select_for_update()
        .first()
    )
    if target is None:
        target = Payout.objects.create(
            farmer=farmer,
            week_start=target_start,
            week_end=target_start + timedelta(days=WEEK_LENGTH_DAYS),
        )

    delivery.payout = target
    delivery.save(update_fields=["payout"])

    if draft.deliveries.exists():
        _refresh_draft(draft)
    else:
        draft.delete()
    _refresh_draft(target)


def edit_delivery(
    delivery: Delivery,
    *,
    delivered_on: date | None = None,
    crop_grade: CropGrade | None = None,
    gross_weight_kg=None,
    moisture_percent=None,
    clock: Clock | None = None,
) -> Delivery:
    """Recalculate an existing ``PROCUREMENT`` delivery and refresh its draft.

    Only the fields supplied are changed; omitted fields keep their stored value.
    Raises :class:`PayoutStateError` when the delivery belongs to a FINALISED or
    PAID payout, and ``ValidationError`` for a non-procurement delivery.
    """
    with transaction.atomic():
        farmer = lock_farmer(delivery.farmer_id)

        # Lock in the agreed order: farmer -> payout -> delivery.
        payout_id = (
            Delivery.objects.filter(pk=delivery.pk)
            .values_list("payout_id", flat=True)
            .first()
        )
        payout = lock_payout(payout_id) if payout_id is not None else None
        locked = Delivery.objects.select_for_update().get(pk=delivery.pk)

        if locked.kind != DeliveryKind.PROCUREMENT:
            raise ValidationError(
                "Only procurement deliveries can be edited.", code="not_editable"
            )

        if payout is not None and payout.status in _SETTLED_STATUSES:
            raise PayoutStateError(
                f"A delivery in a {payout.status} payout cannot be edited."
            )

        new_grade = crop_grade if crop_grade is not None else locked.crop_grade
        new_date = (
            delivered_on if delivered_on is not None else locked.delivered_on
        )
        # Preserve the frozen price unless the pricing basis changed.
        basis_changed = (
            new_grade.pk != locked.crop_grade_id or new_date != locked.delivered_on
        )
        frozen_entry = None
        if not basis_changed and locked.price_list_entry_id is not None:
            frozen_entry = locked.price_list_entry

        preview = _build_preview(
            farmer=farmer,
            crop_grade=new_grade,
            delivered_on=new_date,
            gross_weight_kg=(
                gross_weight_kg
                if gross_weight_kg is not None
                else locked.gross_weight_kg
            ),
            moisture_percent=(
                moisture_percent
                if moisture_percent is not None
                else locked.moisture_percent
            ),
            clock=clock,
            price_entry=frozen_entry,
        )

        locked.crop_grade = preview.crop_grade
        locked.delivered_on = preview.delivered_on
        locked.accounting_date = preview.accounting_date
        locked.gross_weight_kg = preview.gross_weight_kg
        locked.moisture_percent = preview.moisture_percent
        locked.threshold_used = preview.threshold_used
        locked.deduction_percent = preview.deduction_percent
        locked.deduction_kg = preview.deduction_kg
        locked.net_kg = preview.net_kg
        locked.applied_price = preview.applied_price
        locked.price_list_entry = preview.price_list_entry
        locked.amount = preview.amount
        locked.save(
            update_fields=[
                "crop_grade",
                "delivered_on",
                "accounting_date",
                "gross_weight_kg",
                "moisture_percent",
                "threshold_used",
                "deduction_percent",
                "deduction_kg",
                "net_kg",
                "applied_price",
                "price_list_entry",
                "amount",
            ]
        )

        if payout is not None:
            _reconcile_draft(locked, payout, farmer)

    return locked
