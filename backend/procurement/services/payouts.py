"""Weekly payout grouping and finalisation.

Grouping (assignment rule)
--------------------------
A week is Monday..Sunday; the requested ``week_start`` is **normalised** to that
Monday, so any day in the week maps to the same DRAFT. :func:`build_weekly_payout`
attaches the farmer's unassigned deliveries (and correction notes) whose
``accounting_date`` falls in the week to that week's DRAFT payout, using the
**stored** ``amount`` (never a freshly resolved price). It is idempotent and
returns ``None`` for an empty week; when the week is already finalised and there
is nothing new to add it raises :class:`PayoutStateError` (late records get a
supplementary payout instead).

Membership changes and the recomputed DRAFT totals happen together under the
farmer lock, so membership and ``gross_amount``/``net_amount`` stay consistent.
Generating or refreshing a DRAFT never touches the outstanding advance.

Finalisation
------------
:func:`finalise_payout` freezes the payout and recovers
``min(outstanding_advance, 30% of gross_amount)`` from the farmer's balance,
exactly once. Every write is atomic and locks farmer -> payout -> deliveries.

Settlement
----------
:func:`mark_payout_paid` performs the only approved settlement transition,
FINALISED -> PAID, and preserves every frozen financial value. It never recovers
the advance again (the balance is already net of the finalised deduction), so a
repeated or concurrent call cannot double-recover. A non-positive ``net_amount``
(a debit-note-only week, for instance) is payable as-is: recovery is already zero
for a non-positive gross (see :func:`procurement.services.money.advance_recovery`)
and no additional rule is invented here.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from procurement.clock import week_bounds
from procurement.models import Delivery, Farmer, Payout, PayoutStatus
from procurement.precision import validate_decimal_field

from .errors import PayoutStateError
from .locking import lock_deliveries, lock_farmer, lock_payout
from .money import advance_recovery, quantize_money

__all__ = [
    "PayoutStateError",
    "build_weekly_payout",
    "finalise_payout",
    "mark_payout_paid",
]

ZERO = Decimal("0.00")
_SETTLED_STATUSES = (PayoutStatus.FINALISED, PayoutStatus.PAID)


def _refresh_totals(payout: Payout) -> Payout:
    """Recompute a DRAFT payout's totals from its current membership."""
    gross = quantize_money(sum((d.amount for d in payout.deliveries.all()), ZERO))
    validate_decimal_field(gross, Payout, "gross_amount")
    validate_decimal_field(gross, Payout, "net_amount")
    # A draft never reduces the balance; net tracks gross until finalised.
    if payout.gross_amount != gross or payout.net_amount != gross:
        payout.gross_amount = gross
        payout.net_amount = gross
        payout.save(update_fields=["gross_amount", "net_amount"])
    return payout


def build_weekly_payout(farmer: Farmer, week_start: date) -> Payout | None:
    """Create or extend the DRAFT payout for the Monday..Sunday week.

    ``week_start`` may be any day in the target week; it is normalised to the
    Monday. Repeated calls reuse the same DRAFT (no duplicates). Returns ``None``
    for an empty week (no DRAFT and nothing to add), and raises
    :class:`PayoutStateError` when the week is settled with nothing new to add.
    """
    if farmer is None or getattr(farmer, "pk", None) is None:
        raise ValidationError("A saved farmer is required.", code="farmer_required")
    if week_start is None:
        raise ValidationError("week_start is required.", code="required")

    monday, sunday = week_bounds(week_start)

    with transaction.atomic():
        lock_farmer(farmer.pk)

        draft = (
            Payout.objects.filter(
                farmer=farmer, week_start=monday, status=PayoutStatus.DRAFT
            )
            .select_for_update()
            .first()
        )
        unassigned = Delivery.objects.filter(
            farmer=farmer,
            payout__isnull=True,
            accounting_date__gte=monday,
            accounting_date__lte=sunday,
        )
        deliveries = lock_deliveries(unassigned)

        if deliveries:
            if draft is None:
                draft = Payout.objects.create(
                    farmer=farmer, week_start=monday, week_end=sunday
                )
            for delivery in deliveries:
                delivery.payout = draft
                delivery.save(update_fields=["payout"])
            return _refresh_totals(draft)

        if draft is not None:
            return _refresh_totals(draft)

        already_settled = Payout.objects.filter(
            farmer=farmer, week_start=monday, status__in=_SETTLED_STATUSES
        ).exists()
        if already_settled:
            raise PayoutStateError(
                "This week already has a finalised payout; new records need a "
                "supplementary payout."
            )
        return None


def finalise_payout(payout: Payout) -> Payout:
    """Finalise ``payout``, recover any advance, and freeze the totals.

    Runs in a single ``transaction.atomic()`` block. Locks are taken in the
    canonical order (farmer -> payout -> deliveries by pk); the membership is
    re-validated (every included delivery belongs to the payout's farmer) and the
    totals are recomputed from the stored delivery snapshots. The recovery is the
    documented ``min(outstanding_advance, floor_to_cents(30% of gross_amount))``
    taken from the *locked* balance, and it reduces ``outstanding_advance``
    exactly once.

    Only a DRAFT payout can be finalised; a FINALISED/PAID payout raises
    :class:`PayoutStateError` before any write, so a repeated (or concurrent)
    finalisation never applies recovery again.
    """
    if payout is None or getattr(payout, "pk", None) is None:
        raise ValidationError("A saved payout is required.", code="required")

    with transaction.atomic():
        farmer = lock_farmer(payout.farmer_id)
        locked = lock_payout(payout.pk)
        if locked.status != PayoutStatus.DRAFT:
            raise PayoutStateError(
                f"Only a draft payout can be finalised; this payout is {locked.status}."
            )

        deliveries = lock_deliveries(locked.deliveries.all())
        for delivery in deliveries:
            if delivery.farmer_id != locked.farmer_id:
                raise PayoutStateError(
                    "Payout membership is inconsistent: delivery "
                    f"{delivery.pk} belongs to farmer {delivery.farmer_id}, not "
                    f"{locked.farmer_id}."
                )

        gross = quantize_money(sum((d.amount for d in deliveries), ZERO))
        validate_decimal_field(gross, Payout, "gross_amount")
        deduction = advance_recovery(gross, farmer.outstanding_advance)
        validate_decimal_field(deduction, Payout, "advance_deduction")
        net = quantize_money(gross - deduction)
        validate_decimal_field(net, Payout, "net_amount")
        new_outstanding = quantize_money(farmer.outstanding_advance - deduction)
        validate_decimal_field(new_outstanding, Farmer, "outstanding_advance")

        locked.gross_amount = gross
        locked.advance_deduction = deduction
        locked.net_amount = net
        locked.status = PayoutStatus.FINALISED
        locked.finalised_at = timezone.now()
        locked.paid_at = None
        locked.save(
            update_fields=[
                "gross_amount",
                "advance_deduction",
                "net_amount",
                "status",
                "finalised_at",
                "paid_at",
            ]
        )

        farmer.outstanding_advance = new_outstanding
        farmer.save(update_fields=["outstanding_advance"])

    payout.refresh_from_db()
    return payout


def mark_payout_paid(payout: Payout) -> Payout:
    """Settle a FINALISED payout: the only approved transition is FINALISED -> PAID.

    The frozen ``gross_amount``/``advance_deduction``/``net_amount`` and the
    farmer's ``outstanding_advance`` are left untouched -- the advance was already
    recovered at finalisation, so this never recovers it again. A DRAFT (not yet
    finalised) or an already-PAID payout raises :class:`PayoutStateError`. A
    non-positive ``net_amount`` is payable as-is (see the module docstring).
    """
    if payout is None or getattr(payout, "pk", None) is None:
        raise ValidationError("A saved payout is required.", code="required")

    with transaction.atomic():
        lock_farmer(payout.farmer_id)
        locked = lock_payout(payout.pk)
        if locked.status != PayoutStatus.FINALISED:
            raise PayoutStateError(
                "Only a finalised payout can be marked paid; this payout is "
                f"{locked.status}."
            )
        locked.status = PayoutStatus.PAID
        locked.paid_at = timezone.now()
        locked.save(update_fields=["status", "paid_at"])

    payout.refresh_from_db()
    return payout
