"""Pure monetary calculations for advance recovery. No database access.

Kept separate from :mod:`procurement.services.payouts` so the arithmetic can be
unit-tested (and reasoned about) without a database.
"""

from decimal import Decimal

from procurement.precision import MONEY_PLACES, quantize

#: Fraction of a week's gross amount that may be recovered from an outstanding
#: advance. Assignment rule; see README section 8.
ADVANCE_RECOVERY_RATE = Decimal("0.30")


def quantize_money(value) -> Decimal:
    """Round ``value`` to 2 decimal places (ROUND_HALF_UP)."""
    return quantize(value, MONEY_PLACES)


def advance_recovery_cap(
    gross_amount, rate: Decimal = ADVANCE_RECOVERY_RATE
) -> Decimal:
    """Return the most that may be recovered from ``gross_amount`` this week."""
    return quantize_money(Decimal(gross_amount) * rate)


def advance_recovery(
    gross_amount, outstanding_advance, rate: Decimal = ADVANCE_RECOVERY_RATE
) -> Decimal:
    """Return the advance amount to recover: capped by rate, never overdrawn.

    ``min(outstanding_advance, 30% of gross_amount)``, quantised to 2 dp. A zero
    gross amount or zero outstanding balance recovers nothing.
    """
    outstanding = quantize_money(outstanding_advance)
    if gross_amount <= 0 or outstanding <= 0:
        return Decimal("0.00")
    return quantize_money(min(outstanding, advance_recovery_cap(gross_amount, rate)))
