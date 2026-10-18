"""Credit/debit note corrections (assignment rule: immutability).

A correction adjusts a delivery that has already been finalised or paid; the
original is never rewritten. The note inherits the original's farmer, is stamped
with the **business date** it is recorded (``get_clock().today()``) -- which,
not the original ``delivered_on``, selects the payout week -- and carries a
signed ``amount`` (credit ``+``, debit ``-``) plus the positive
``correction_magnitude`` and a reason.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from procurement.clock import Clock, get_clock
from procurement.models import (
    GRADE_NOTE_KINDS,
    Delivery,
    DeliveryKind,
    PayoutStatus,
)
from procurement.precision import MONEY_PLACES, quantize, validate_precision

from .locking import lock_farmer, lock_payout
from .validation import as_decimal

__all__ = ["record_correction"]

CORRECTION_SIGNS = {
    DeliveryKind.CREDIT_NOTE: Decimal(1),
    DeliveryKind.DEBIT_NOTE: Decimal(-1),
}
_CORRECTABLE_STATUSES = (PayoutStatus.FINALISED, PayoutStatus.PAID)


def record_correction(
    original_delivery: Delivery,
    kind: str,
    magnitude,
    reason: str,
    *,
    clock: Clock | None = None,
) -> Delivery:
    """Record a credit/debit note against a finalised or paid delivery.

    ``clock`` (a :class:`~procurement.clock.Clock`) is injected for the business
    date; it defaults to :func:`~procurement.clock.get_clock`.
    """
    if kind not in GRADE_NOTE_KINDS:
        raise ValidationError(
            "kind must be a credit or debit note.", code="invalid_kind"
        )

    value = as_decimal(magnitude, "magnitude")
    validate_precision(value, MONEY_PLACES, "magnitude")
    if value <= 0:
        raise ValidationError(
            "Correction magnitude must be greater than zero.", code="not_positive"
        )
    if not reason or not str(reason).strip():
        raise ValidationError(
            "A correction reason is required.", code="reason_required"
        )

    with transaction.atomic():
        farmer = lock_farmer(original_delivery.farmer_id)

        original_payout = original_delivery.payout
        if (
            original_payout is None
            or original_payout.status not in _CORRECTABLE_STATUSES
        ):
            raise ValidationError(
                "Corrections can only be recorded against a finalised or paid "
                "delivery.",
                code="original_not_settled",
            )
        lock_payout(original_payout.pk)

        sign = CORRECTION_SIGNS[kind]
        return Delivery.objects.create(
            farmer=farmer,
            kind=kind,
            original_delivery=original_delivery,
            correction_magnitude=quantize(value, MONEY_PLACES),
            reason=reason,
            accounting_date=(clock or get_clock()).today(),
            amount=quantize(value * sign, MONEY_PLACES),
        )
