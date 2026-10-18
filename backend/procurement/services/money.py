"""Pure monetary calculations for advance recovery. No database access.

Kept separate from :mod:`procurement.services.payouts` so the arithmetic can be
unit-tested (and reasoned about) without a database.
"""

from decimal import ROUND_DOWN, Decimal

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
    """Round a positive percentage cap down so recovery never exceeds it."""
    gross = Decimal(gross_amount)
    if gross <= 0:
        return Decimal("0.00")
    exact_cap = gross * rate
    quantum = Decimal(1).scaleb(-MONEY_PLACES)
    return exact_cap.quantize(quantum, rounding=ROUND_DOWN)


def advance_recovery(
    gross_amount, outstanding_advance, rate: Decimal = ADVANCE_RECOVERY_RATE
) -> Decimal:
    """Return the advance amount to recover: capped by rate, never overdrawn.

    ``min(outstanding_advance, floor_to_cents(30% of gross_amount))``. A zero
    or negative gross amount or zero outstanding balance recovers nothing.
    """
    outstanding = quantize_money(outstanding_advance)
    if gross_amount <= 0 or outstanding <= 0:
        return Decimal("0.00")
    return quantize_money(min(outstanding, advance_recovery_cap(gross_amount, rate)))
