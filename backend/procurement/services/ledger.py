"""Read-only farmer ledger.

:func:`build_farmer_ledger` assembles a single immutable snapshot of one
farmer's financial history -- deliveries and correction notes, advances,
payouts (with their status and arithmetic), the recorded outstanding advance and
the advance reconciliation -- **without writing anything**. It is the read model
the API/serializers should project; the write paths stay in the per-domain
service modules.

No double counting
------------------
A delivery/note is an earning recorded **once**; a payout references its members
through the single ``Delivery.payout`` foreign key and never adds a second
earning of its own. ``LedgerPayout.member_total`` is recomputed from the ledger's
delivery rows (not trusted from the stored column) and ``gross_matches_members``
records whether the stored ``gross_amount`` agrees, so the caller can assert

    settled_earnings + draft_projection + unassigned_earnings
        == total_recorded_amount

(see :attr:`FarmerLedger.earnings_identity_holds`). That identity only holds if a
delivery and its payout are *not* added as two independent earnings.

Draft projections vs finalised recoveries
-----------------------------------------
DRAFT payouts are **projections**: their ``advance_deduction`` is zero and they
never reduced the balance. Only FINALISED/PAID payouts carry a real recovery.
The ledger keeps them apart -- :attr:`FarmerLedger.draft_payouts` /
``draft_projection`` versus :attr:`FarmerLedger.settled_payouts` /
``settled_earnings`` / ``total_recovered`` -- so a projection is never mistaken
for money already recovered.

Deterministic ordering
----------------------
Deliveries are ordered by ``(accounting_date, kind, pk)``, advances by
``(given_on, pk)`` and payouts by ``(week_start, status, pk)``; member ids are in
``pk`` order. Two calls on unchanged data return equal tuples.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from procurement.models import (
    GRADE_NOTE_KINDS,
    Advance,
    Delivery,
    Farmer,
    Payout,
    PayoutStatus,
)

from .advances import AdvanceReconciliation, reconcile_outstanding
from .money import quantize_money

__all__ = [
    "FarmerLedger",
    "LedgerAdvance",
    "LedgerDelivery",
    "LedgerPayout",
    "build_farmer_ledger",
]

ZERO = Decimal("0.00")
_SETTLED_STATUSES = (PayoutStatus.FINALISED, PayoutStatus.PAID)


def _money(value) -> Decimal:
    return ZERO if value is None else value


@dataclass(frozen=True)
class LedgerDelivery:
    """One delivery or correction note, with its payout assignment."""

    id: int
    kind: str
    crop_grade_id: int | None
    delivered_on: date | None
    accounting_date: date | None
    gross_weight_kg: Decimal | None
    moisture_percent: Decimal | None
    net_kg: Decimal | None
    applied_price: Decimal | None
    amount: Decimal | None
    payout_id: int | None
    original_delivery_id: int | None
    correction_magnitude: Decimal | None
    reason: str

    @property
    def is_correction(self) -> bool:
        return self.kind in GRADE_NOTE_KINDS

    @property
    def is_assigned(self) -> bool:
        return self.payout_id is not None

    @property
    def signed_amount(self) -> Decimal:
        return _money(self.amount)


@dataclass(frozen=True)
class LedgerAdvance:
    """One advance, keyed by its own identity (never by farmer/date alone)."""

    id: int
    amount: Decimal
    given_on: date
    created_at: datetime


@dataclass(frozen=True)
class LedgerPayout:
    """One payout with its frozen arithmetic and its member deliveries."""

    id: int
    week_start: date
    week_end: date
    status: str
    gross_amount: Decimal
    advance_deduction: Decimal
    net_amount: Decimal
    finalised_at: datetime | None
    paid_at: datetime | None
    delivery_ids: tuple[int, ...]
    member_total: Decimal

    @property
    def is_draft(self) -> bool:
        return self.status == PayoutStatus.DRAFT

    @property
    def is_settled(self) -> bool:
        return self.status in _SETTLED_STATUSES

    @property
    def gross_matches_members(self) -> bool:
        """Stored gross equals the sum of the current member amounts."""
        return self.gross_amount == self.member_total

    @property
    def net_equals_gross_minus_deduction(self) -> bool:
        return self.net_amount == self.gross_amount - self.advance_deduction


@dataclass(frozen=True)
class FarmerLedger:
    """Immutable read-only snapshot of one farmer's ledger."""

    farmer_id: int
    name: str
    phone: str
    outstanding_advance: Decimal
    advances: tuple[LedgerAdvance, ...]
    deliveries: tuple[LedgerDelivery, ...]
    payouts: tuple[LedgerPayout, ...]
    reconciliation: AdvanceReconciliation

    @property
    def total_advances(self) -> Decimal:
        return quantize_money(sum((a.amount for a in self.advances), ZERO))

    @property
    def settled_payouts(self) -> tuple[LedgerPayout, ...]:
        return tuple(p for p in self.payouts if p.is_settled)

    @property
    def draft_payouts(self) -> tuple[LedgerPayout, ...]:
        return tuple(p for p in self.payouts if p.is_draft)

    @property
    def settled_earnings(self) -> Decimal:
        """Gross of FINALISED/PAID payouts -- earnings already locked in."""
        return quantize_money(sum((p.gross_amount for p in self.settled_payouts), ZERO))

    @property
    def total_recovered(self) -> Decimal:
        """Advance actually recovered by FINALISED/PAID payouts."""
        return quantize_money(
            sum((p.advance_deduction for p in self.settled_payouts), ZERO)
        )

    @property
    def draft_projection(self) -> Decimal:
        """Gross of DRAFT payouts -- a projection, not yet an earning."""
        return quantize_money(sum((p.gross_amount for p in self.draft_payouts), ZERO))

    @property
    def unassigned_deliveries(self) -> tuple[LedgerDelivery, ...]:
        return tuple(d for d in self.deliveries if not d.is_assigned)

    @property
    def unassigned_earnings(self) -> Decimal:
        return quantize_money(
            sum((d.signed_amount for d in self.unassigned_deliveries), ZERO)
        )

    @property
    def total_recorded_amount(self) -> Decimal:
        """Every delivery/note amount counted exactly once."""
        return quantize_money(sum((d.signed_amount for d in self.deliveries), ZERO))

    @property
    def earnings_identity_holds(self) -> bool:
        """No delivery is counted twice (once itself and once via its payout)."""
        return (
            self.settled_earnings
            + self.draft_projection
            + self.unassigned_earnings
            == self.total_recorded_amount
        )

    @property
    def is_reconciled(self) -> bool:
        return self.reconciliation.is_reconciled


def build_farmer_ledger(farmer: Farmer) -> FarmerLedger:
    """Return the read-only ledger snapshot for ``farmer``.

    Reads run in one ``transaction.atomic()`` block so the snapshot is
    consistent. No row is created, updated or deleted; nothing is materialised
    beyond the returned frozen dataclasses.
    """
    if farmer is None or getattr(farmer, "pk", None) is None:
        raise ValidationError("A saved farmer is required.", code="farmer_required")

    with transaction.atomic():
        farmer.refresh_from_db(
            fields=["name", "phone", "outstanding_advance"],
        )

        advances = tuple(
            LedgerAdvance(
                id=row.id,
                amount=row.amount,
                given_on=row.given_on,
                created_at=row.created_at,
            )
            for row in Advance.objects.filter(farmer=farmer).order_by("given_on", "pk")
        )

        deliveries = tuple(
            LedgerDelivery(
                id=row.id,
                kind=row.kind,
                crop_grade_id=row.crop_grade_id,
                delivered_on=row.delivered_on,
                accounting_date=row.accounting_date,
                gross_weight_kg=row.gross_weight_kg,
                moisture_percent=row.moisture_percent,
                net_kg=row.net_kg,
                applied_price=row.applied_price,
                amount=row.amount,
                payout_id=row.payout_id,
                original_delivery_id=row.original_delivery_id,
                correction_magnitude=row.correction_magnitude,
                reason=row.reason,
            )
            for row in Delivery.objects.filter(farmer=farmer).order_by(
                "accounting_date", "kind", "pk"
            )
        )

        members: dict[int, list[LedgerDelivery]] = {}
        for delivery in deliveries:
            if delivery.payout_id is not None:
                members.setdefault(delivery.payout_id, []).append(delivery)

        payouts = tuple(
            LedgerPayout(
                id=row.id,
                week_start=row.week_start,
                week_end=row.week_end,
                status=row.status,
                gross_amount=row.gross_amount,
                advance_deduction=row.advance_deduction,
                net_amount=row.net_amount,
                finalised_at=row.finalised_at,
                paid_at=row.paid_at,
                delivery_ids=tuple(d.id for d in members.get(row.id, ())),
                member_total=quantize_money(
                    sum(
                        (d.signed_amount for d in members.get(row.id, ())),
                        ZERO,
                    )
                ),
            )
            for row in Payout.objects.filter(farmer=farmer).order_by(
                "week_start", "status", "pk"
            )
        )

        reconciliation = reconcile_outstanding(farmer)

    return FarmerLedger(
        farmer_id=farmer.pk,
        name=farmer.name,
        phone=farmer.phone,
        outstanding_advance=quantize_money(farmer.outstanding_advance),
        advances=advances,
        deliveries=deliveries,
        payouts=payouts,
        reconciliation=reconciliation,
    )
