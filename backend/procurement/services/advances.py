"""Advance posting and reconciliation.

Assignment rule: an advance raises the farmer's outstanding balance. The balance
is the source of truth for later recovery; posting is atomic and locks the farmer
row. Advances are keyed by their own identity -- ``(farmer, given_on)`` is
deliberately **not** unique (see ``procurement.scenarios``), so several advances
may be issued to one farmer on the same date.

Recovery is owned by payout finalisation (:func:`procurement.services.payouts.finalise_payout`);
this module never deducts recovery -- it only posts advances and reconciles the
resulting balance.

Reconciliation
--------------
:func:`reconcile_outstanding` reports whether

    sum(advances) - sum(recovery on FINALISED/PAID payouts)

equals the stored ``Farmer.outstanding_advance``. Each payout contributes its
``advance_deduction`` at most once: ``PAID`` is a later state of the same payout,
not a second recovery. The check is **read-only** -- it never repairs a drifted
balance, so recorded history is preserved and the discrepancy is surfaced
instead.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from procurement.models import Advance, Farmer, Payout, PayoutStatus
from procurement.precision import validate_decimal_field

from .errors import AdvanceReconciliationError
from .locking import lock_farmer
from .money import quantize_money
from .validation import as_decimal

__all__ = [
    "AdvanceReconciliation",
    "AdvanceReconciliationError",
    "assert_outstanding_reconciles",
    "post_advance",
    "reconcile_outstanding",
]

_RECOVERED_STATUSES = (PayoutStatus.FINALISED, PayoutStatus.PAID)
ZERO = Decimal("0.00")


def post_advance(farmer: Farmer, amount, given_on: date) -> Advance:
    """Create an advance and increase the farmer's outstanding balance once.

    The farmer is validated and locked inside the transaction, so concurrent
    advances serialize on the row and none is lost.
    """
    if farmer is None or getattr(farmer, "pk", None) is None:
        raise ValidationError("A saved farmer is required.", code="farmer_required")
    value = as_decimal(amount, "amount")
    validate_decimal_field(value, Advance, "amount")
    if value <= 0:
        raise ValidationError(
            "Advance amount must be greater than zero.", code="not_positive"
        )
    if given_on is None:
        raise ValidationError("given_on is required.", code="required")

    with transaction.atomic():
        locked = lock_farmer(farmer.pk)
        new_outstanding = quantize_money(locked.outstanding_advance + value)
        validate_decimal_field(new_outstanding, Farmer, "outstanding_advance")
        advance = Advance.objects.create(
            farmer=farmer, amount=quantize_money(value), given_on=given_on
        )
        locked.outstanding_advance = new_outstanding
        locked.save(update_fields=["outstanding_advance"])
    return advance


@dataclass(frozen=True)
class AdvanceReconciliation:
    """Advance/recovery reconciliation for one farmer."""

    farmer_id: int
    total_advances: Decimal
    total_recovered: Decimal
    expected_outstanding: Decimal
    stored_outstanding: Decimal

    @property
    def difference(self) -> Decimal:
        """Stored balance minus the balance implied by advances and recoveries."""
        return self.stored_outstanding - self.expected_outstanding

    @property
    def is_reconciled(self) -> bool:
        return self.difference == ZERO


def reconcile_outstanding(farmer: Farmer) -> AdvanceReconciliation:
    """Return the (read-only) advance reconciliation for ``farmer``."""
    total_advances = quantize_money(
        Advance.objects.filter(farmer=farmer).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    total_recovered = quantize_money(
        Payout.objects.filter(farmer=farmer, status__in=_RECOVERED_STATUSES).aggregate(
            total=Sum("advance_deduction")
        )["total"]
        or ZERO
    )
    expected = quantize_money(total_advances - total_recovered)

    farmer.refresh_from_db(fields=["outstanding_advance"])
    return AdvanceReconciliation(
        farmer_id=farmer.pk,
        total_advances=total_advances,
        total_recovered=total_recovered,
        expected_outstanding=expected,
        stored_outstanding=quantize_money(farmer.outstanding_advance),
    )


def assert_outstanding_reconciles(farmer: Farmer) -> AdvanceReconciliation:
    """Return the reconciliation, raising if the stored balance has drifted.

    Read-only: a drifted balance is reported, never silently repaired.
    """
    reconciliation = reconcile_outstanding(farmer)
    if not reconciliation.is_reconciled:
        raise AdvanceReconciliationError(
            f"Farmer {farmer.pk}: advances {reconciliation.total_advances} - "
            f"recovered {reconciliation.total_recovered} = "
            f"{reconciliation.expected_outstanding}, but stored outstanding is "
            f"{reconciliation.stored_outstanding}."
        )
    return reconciliation
