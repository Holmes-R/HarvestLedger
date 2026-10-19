"""Credit/debit note corrections (assignment rule: immutability).

A correction adjusts a delivery that has already been finalised or paid; the
original is never rewritten and the finalised statement it belongs to is left
untouched. The note inherits the original's farmer (so the correction always
stays with the same farmer as the original -- the service takes no separate
farmer), is stamped with the **business date** it is recorded
(``get_clock().today()``) -- which, not the original ``delivered_on``, selects
the payout week -- and carries a signed ``amount`` (credit ``+``, debit ``-``)
plus the positive ``correction_magnitude`` and a reason.

A correction is an ordinary ``Delivery`` of kind ``CREDIT_NOTE``/``DEBIT_NOTE``
-- never a fake negative ordinary weight -- and is pulled into exactly one payout
by ``procurement.services.payouts.build_weekly_payout`` through the single
``Delivery.payout`` foreign key. Nothing restricts an original to a single note:
several corrections may reference the same original, each entering one payout.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from procurement.clock import Clock, get_clock
from procurement.models import (
    GRADE_NOTE_KINDS,
    Delivery,
    DeliveryKind,
    Payout,
    PayoutStatus,
)
from procurement.precision import MONEY_PLACES, quantize, validate_decimal_field

from .errors import OriginalDeliveryNotFound
from .locking import lock_farmer, lock_payout
from .validation import as_decimal

__all__ = ["OriginalDeliveryNotFound", "record_correction"]

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
    original_pk = getattr(original_delivery, "pk", None)
    if original_pk is None:
        raise ValidationError(
            "An existing original delivery is required.", code="original_required"
        )

    if kind not in GRADE_NOTE_KINDS:
        raise ValidationError(
            "kind must be a credit or debit note.", code="invalid_kind"
        )

    value = as_decimal(magnitude, "magnitude")
    validate_decimal_field(value, Delivery, "correction_magnitude")
    if value <= 0:
        raise ValidationError(
            "Correction magnitude must be greater than zero.", code="not_positive"
        )
    if not reason or not str(reason).strip():
        raise ValidationError(
            "A correction reason is required.", code="reason_required"
        )

    with transaction.atomic():
        # The caller's object supplies only a primary key. Read ownership from
        # PostgreSQL before taking the canonical farmer -> payout -> delivery
        # locks. Recheck after locking: a concurrent edit may have changed the
        # reference between this initial lookup and the locks.
        reference = Delivery.objects.filter(pk=original_pk).values("farmer_id").first()
        if reference is None:
            raise OriginalDeliveryNotFound(
                f"Original delivery {original_pk} was not found."
            )
        farmer = lock_farmer(reference["farmer_id"])
        current = (
            Delivery.objects.filter(pk=original_pk)
            .values("farmer_id", "payout_id")
            .first()
        )
        if current is None:
            raise OriginalDeliveryNotFound(
                f"Original delivery {original_pk} was not found."
            )
        if current["farmer_id"] != farmer.pk:
            raise ValidationError(
                "The original delivery changed while being checked.",
                code="original_changed",
            )
        if current["payout_id"] is None:
            raise ValidationError(
                "Corrections can only be recorded against a finalised or paid "
                "delivery.",
                code="original_not_settled",
            )
        try:
            original_payout = lock_payout(current["payout_id"])
        except Payout.DoesNotExist as exc:
            raise ValidationError(
                "The original payout changed while being checked.",
                code="original_changed",
            ) from exc
        try:
            original = Delivery.objects.select_for_update().get(pk=original_pk)
        except Delivery.DoesNotExist as exc:
            raise OriginalDeliveryNotFound(
                f"Original delivery {original_pk} was not found."
            ) from exc
        if (
            original.farmer_id != farmer.pk
            or original.payout_id != original_payout.pk
            or original_payout.farmer_id != farmer.pk
        ):
            raise ValidationError(
                "The original delivery changed while being checked.",
                code="original_changed",
            )
        if original_payout.status not in _CORRECTABLE_STATUSES:
            raise ValidationError(
                "Corrections can only be recorded against a finalised or paid "
                "delivery.",
                code="original_not_settled",
            )

        sign = CORRECTION_SIGNS[kind]
        signed_amount = quantize(value * sign, MONEY_PLACES)
        validate_decimal_field(signed_amount, Delivery, "amount")
        return Delivery.objects.create(
            farmer=farmer,
            kind=kind,
            original_delivery=original,
            correction_magnitude=quantize(value, MONEY_PLACES),
            reason=reason,
            accounting_date=(clock or get_clock()).today(),
            amount=signed_amount,
        )
