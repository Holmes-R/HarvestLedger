"""Read-only farmer ledger (M2).

The ledger is a projection: it must reconcile with the stored balance, keep a
delivery's earning distinct from its payout (no double counting), separate DRAFT
projections from finalised recoveries, order everything deterministically and
write nothing.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from procurement.models import (
    Advance,
    Delivery,
    Farmer,
    Payout,
)
from procurement.services import ledger

pytestmark = pytest.mark.m2


@pytest.fixture
def seed(db):
    def _run():
        call_command("seed_data", stdout=StringIO())

    return _run


def _financial_snapshot():
    return {
        "advances": list(
            Advance.objects.order_by("pk").values_list(
                "farmer__phone", "amount", "given_on"
            )
        ),
        "deliveries": list(
            Delivery.objects.order_by("pk").values_list(
                "farmer__phone", "kind", "accounting_date", "amount", "payout_id"
            )
        ),
        "payouts": list(
            Payout.objects.order_by("pk").values_list(
                "farmer__phone",
                "week_start",
                "status",
                "gross_amount",
                "advance_deduction",
                "net_amount",
            )
        ),
        "balances": list(
            Farmer.objects.order_by("phone").values_list("phone", "outstanding_advance")
        ),
    }


def test_every_seeded_ledger_reconciles(seed):
    seed()
    for farmer in Farmer.objects.order_by("pk"):
        snapshot = ledger.build_farmer_ledger(farmer)
        assert snapshot.is_reconciled
        assert (
            snapshot.reconciliation.stored_outstanding == snapshot.outstanding_advance
        )
        assert snapshot.total_advances == sum(a.amount for a in snapshot.advances)


def test_ledger_does_not_double_count_delivery_and_payout(seed):
    seed()
    for farmer in Farmer.objects.order_by("pk"):
        snapshot = ledger.build_farmer_ledger(farmer)
        assert snapshot.earnings_identity_holds
        # A payout's gross is the sum of its members, counted once.
        for payout in snapshot.payouts:
            assert payout.gross_matches_members
            assert payout.net_equals_gross_minus_deduction


def test_ledger_keeps_drafts_distinct_from_finalised_recoveries(seed):
    seed()
    farmer = Farmer.objects.get(phone="9000000001")
    snapshot = ledger.build_farmer_ledger(farmer)

    assert snapshot.draft_payouts, "demo should include at least one DRAFT payout"
    assert snapshot.settled_payouts, "demo should include settled payouts"
    # Drafts never reduce the balance, so their recovery is always zero.
    assert all(p.advance_deduction == Decimal("0.00") for p in snapshot.draft_payouts)
    assert snapshot.total_recovered == sum(
        (p.advance_deduction for p in snapshot.settled_payouts), Decimal("0.00")
    )
    assert snapshot.draft_projection == sum(
        (p.gross_amount for p in snapshot.draft_payouts), Decimal("0.00")
    )


def test_ledger_lists_membership_and_advances_in_deterministic_order(seed):
    seed()
    farmer = Farmer.objects.get(phone="9000000002")
    first = ledger.build_farmer_ledger(farmer)
    second = ledger.build_farmer_ledger(farmer)

    assert first == second
    assert first.advances == tuple(
        sorted(first.advances, key=lambda a: (a.given_on, a.id))
    )
    assert first.deliveries == tuple(
        sorted(first.deliveries, key=lambda d: (d.accounting_date, d.kind, d.id))
    )
    assert first.payouts == tuple(
        sorted(first.payouts, key=lambda p: (p.week_start, p.status, p.id))
    )
    # Same-day advances are never collapsed by farmer/date.
    same_day = [a for a in first.advances if a.given_on == date(2026, 1, 5)]
    assert len(same_day) == 2


def test_ledger_is_read_only(seed):
    seed()
    before = _financial_snapshot()
    for farmer in Farmer.objects.order_by("pk"):
        ledger.build_farmer_ledger(farmer)
    assert _financial_snapshot() == before


def test_ledger_requires_a_saved_farmer():
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError) as excinfo:
        ledger.build_farmer_ledger(Farmer(name="Unsaved"))
    assert excinfo.value.code == "farmer_required"
