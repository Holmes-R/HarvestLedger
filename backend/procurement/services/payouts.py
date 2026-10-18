"""Weekly payout grouping and finalisation.

Grouping (assignment rule)
--------------------------
A week is Monday..Sunday. :func:`build_weekly_payout` attaches a farmer's
unassigned deliveries (and correction notes) whose ``accounting_date`` falls in
the week to that week's DRAFT payout. It is idempotent, returns ``None`` for an
empty week, and raises :class:`PayoutStateError` when the week is already
finalised and there is nothing new to add (late records get a supplementary
payout instead).

Finalisation
------------
:func:`finalise_payout` freezes the payout and recovers
``min(outstanding_advance, 30% of gross_amount)`` from the farmer's balance,
exactly once. Every write is atomic and locks farmer -> payout -> deliveries.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from procurement.models import Delivery, Farmer, Payout, PayoutStatus

from .errors import PayoutStateError
from .locking import lock_deliveries, lock_farmer, lock_payout
from .money import advance_recovery, quantize_money

__all__ = ["PayoutStateError", "build_weekly_payout", "finalise_payout"]

WEEK_LENGTH_DAYS = 6
ZERO = Decimal("0.00")
_SETTLED_STATUSES = (PayoutStatus.FINALISED, PayoutStatus.PAID)


def build_weekly_payout(farmer: Farmer, week_start: date) -> Payout | None:
    """Create or extend the DRAFT payout for the week beginning ``week_start``."""
    week_end = week_start + timedelta(days=WEEK_LENGTH_DAYS)

    with transaction.atomic():
        lock_farmer(farmer.pk)

        draft = (
            Payout.objects.filter(
                farmer=farmer, week_start=week_start, status=PayoutStatus.DRAFT
            )
            .select_for_update()
            .first()
        )
        unassigned = Delivery.objects.filter(
            farmer=farmer,
            payout__isnull=True,
            accounting_date__gte=week_start,
            accounting_date__lte=week_end,
        )
        deliveries = lock_deliveries(unassigned)

        if deliveries:
            if draft is None:
                draft = Payout.objects.create(
                    farmer=farmer, week_start=week_start, week_end=week_end
                )
            for delivery in deliveries:
                delivery.payout = draft
                delivery.save(update_fields=["payout"])

            gross = quantize_money(
                sum((d.amount for d in draft.deliveries.all()), ZERO)
            )
            draft.gross_amount = gross
            # A draft never reduces the balance; net tracks gross until finalised.
            draft.net_amount = gross
            draft.save(update_fields=["gross_amount", "net_amount"])
            return draft

        if draft is not None:
            return draft

        already_settled = Payout.objects.filter(
            farmer=farmer, week_start=week_start, status__in=_SETTLED_STATUSES
        ).exists()
        if already_settled:
            raise PayoutStateError(
                "This week already has a finalised payout; new records need a "
                "supplementary payout."
            )
        return None


def finalise_payout(payout: Payout) -> Payout:
    """Finalise ``payout``, recover any advance, and freeze the totals."""
    with transaction.atomic():
        farmer = lock_farmer(payout.farmer_id)
        locked = lock_payout(payout.pk)
        if locked.status != PayoutStatus.DRAFT:
            raise PayoutStateError(
                f"Only a draft payout can be finalised; this payout is {locked.status}."
            )

        deliveries = lock_deliveries(locked.deliveries.all())
        gross = quantize_money(sum((d.amount for d in deliveries), ZERO))
        deduction = advance_recovery(gross, farmer.outstanding_advance)

        locked.gross_amount = gross
        locked.advance_deduction = deduction
        locked.net_amount = quantize_money(gross - deduction)
        locked.status = PayoutStatus.FINALISED
        locked.finalised_at = timezone.now()
        locked.save(
            update_fields=[
                "gross_amount",
                "advance_deduction",
                "net_amount",
                "status",
                "finalised_at",
            ]
        )

        farmer.outstanding_advance = quantize_money(
            farmer.outstanding_advance - deduction
        )
        farmer.save(update_fields=["outstanding_advance"])

    payout.refresh_from_db()
    return payout
