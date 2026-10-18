"""M2 scenario manifest (declarative documentation).

This module describes the financial situations the M2 service layer and payout
engine handle. It is **data only**: importing it writes nothing. The M2 services
now exist; ``python manage.py seed_data`` executes a comparable demo subset
through those services, while this manifest stays a readable specification the
tests reference.

Coverage
--------
* multiple weeks (Monday-Sunday),
* moisture boundaries (below / at / just above / cap / above max),
* missing rates (``PRICE_NOT_FOUND``),
* backdated price entries (effective-dated selection),
* large advances (recovery cap and carry-forward),
* finalised deliveries and correction notes (next eligible payout).

Advance deduplication
---------------------
`ADVANCE_DEDUPLICATION_NOTE` states the rule explicitly: several advances may be
issued to one farmer on one date, so ``(farmer, given_on)`` is **not** an
advance deduplication key. Scenario ``large-advance`` includes two advances with
the same farmer and date to pin this.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ADVANCE_DEDUPLICATION_NOTE = (
    "Multiple advances can occur for one farmer on one date. Do not use "
    "(farmer, given_on) as an advance deduplication key; give every advance its "
    "own identity."
)

WEEK_1 = (date(2026, 1, 5), date(2026, 1, 11))
WEEK_2 = (date(2026, 1, 12), date(2026, 1, 18))
WEEK_3 = (date(2026, 1, 19), date(2026, 1, 25))


@dataclass(frozen=True)
class PriceSpec:
    crop_key: str
    grade_code: str
    price_per_kg: Decimal
    effective_from: date
    note: str = ""


@dataclass(frozen=True)
class AdvanceSpec:
    key: str
    farmer_key: str
    amount: Decimal
    given_on: date


@dataclass(frozen=True)
class DeliverySpec:
    key: str
    farmer_key: str
    crop_key: str
    grade_code: str
    delivered_on: date
    gross_weight_kg: Decimal
    moisture_percent: Decimal


@dataclass(frozen=True)
class CorrectionSpec:
    key: str
    original_delivery_key: str
    kind: str  # CREDIT_NOTE | DEBIT_NOTE
    correction_magnitude: Decimal
    recorded_on: date
    reason: str


@dataclass(frozen=True)
class Scenario:
    key: str
    description: str
    expected: tuple[str, ...]
    prices: tuple[PriceSpec, ...] = ()
    advances: tuple[AdvanceSpec, ...] = ()
    deliveries: tuple[DeliverySpec, ...] = ()
    corrections: tuple[CorrectionSpec, ...] = ()


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="multiple-weeks",
        description="One farmer delivers in three consecutive weeks.",
        expected=(
            (
                "Three Draft payouts, one per Monday-Sunday week, each containing "
                "only that week's deliveries."
            ),
            "Sunday 2026-01-11 is in WEEK_1; Monday 2026-01-12 opens WEEK_2.",
        ),
        deliveries=(
            DeliverySpec(
                "MW-1",
                "FARMER-1",
                "MAIZE",
                "A",
                WEEK_1[0],
                Decimal("120.000"),
                Decimal("14.00"),
            ),
            DeliverySpec(
                "MW-2",
                "FARMER-1",
                "MAIZE",
                "A",
                WEEK_2[0],
                Decimal("80.500"),
                Decimal("14.00"),
            ),
            DeliverySpec(
                "MW-3",
                "FARMER-1",
                "MAIZE",
                "A",
                WEEK_3[1],
                Decimal("60.250"),
                Decimal("14.00"),
            ),
        ),
    ),
    Scenario(
        key="moisture-boundaries",
        description="Moisture at and around the deduction boundaries (Maize, "
        "threshold 14.00, max 20.00).",
        expected=(
            "13.00 (below) -> 0% deduction",
            "14.00 (at threshold) -> 0% deduction",
            "15.99 (fractional excess) -> floor to 1%",
            "19.99 (near max) -> floor to 5%",
            "20.01 (above max) -> rejected, no row written",
        ),
        deliveries=(
            DeliverySpec(
                "MB-BELOW",
                "FARMER-1",
                "MAIZE",
                "A",
                WEEK_1[0],
                Decimal("100.000"),
                Decimal("13.00"),
            ),
            DeliverySpec(
                "MB-AT",
                "FARMER-1",
                "MAIZE",
                "A",
                WEEK_1[0],
                Decimal("100.000"),
                Decimal("14.00"),
            ),
            DeliverySpec(
                "MB-FRACTION",
                "FARMER-1",
                "MAIZE",
                "A",
                date(2026, 1, 6),
                Decimal("100.000"),
                Decimal("15.99"),
            ),
            DeliverySpec(
                "MB-NEAR-MAX",
                "FARMER-1",
                "MAIZE",
                "A",
                date(2026, 1, 7),
                Decimal("100.000"),
                Decimal("19.99"),
            ),
            DeliverySpec(
                "MB-OVER-MAX",
                "FARMER-1",
                "MAIZE",
                "A",
                date(2026, 1, 8),
                Decimal("100.000"),
                Decimal("20.01"),
            ),
        ),
    ),
    Scenario(
        key="missing-rate",
        description="Deliveries with no price effective on or before their date.",
        expected=(
            "PRICE_NOT_FOUND naming the crop/grade and date; nothing written.",
            "A grade that only has a future price is missing for an earlier delivery.",
        ),
        prices=(
            PriceSpec("PADDY", "A", Decimal("26.00"), date(2025, 11, 1)),
            PriceSpec("PADDY", "B", Decimal("23.00"), date(2026, 1, 1)),
        ),
        deliveries=(
            DeliverySpec(
                "MR-BEFORE-FIRST",
                "FARMER-3",
                "PADDY",
                "A",
                date(2025, 10, 15),
                Decimal("100.000"),
                Decimal("12.00"),
            ),
            DeliverySpec(
                "MR-GRADE-ONLY-FUTURE",
                "FARMER-3",
                "PADDY",
                "B",
                date(2025, 12, 1),
                Decimal("100.000"),
                Decimal("12.00"),
            ),
        ),
    ),
    Scenario(
        key="backdated-price",
        description="A price entry is added later with an earlier effective date.",
        expected=(
            (
                "A delivery is priced with the latest entry effective on or before "
                "delivered_on -- here the backdated 2025-12-15 rate (23.00), not "
                "the 2026-01-01 rate."
            ),
        ),
        prices=(
            PriceSpec("MAIZE", "A", Decimal("24.50"), date(2026, 1, 1)),
            PriceSpec(
                "MAIZE",
                "A",
                Decimal("23.00"),
                date(2025, 12, 15),
                note="backdated, inserted after the 2026-01-01 entry",
            ),
        ),
        deliveries=(
            DeliverySpec(
                "BP-1",
                "FARMER-1",
                "MAIZE",
                "A",
                date(2025, 12, 20),
                Decimal("100.000"),
                Decimal("14.00"),
            ),
        ),
    ),
    Scenario(
        key="large-advance",
        description="Advances larger than a week's gross, plus two advances to "
        "one farmer on the same date.",
        expected=(
            ("advance_deduction = min(outstanding_advance, 30% of gross_amount)"),
            "the remainder carries forward to later weeks",
            "both same-day advances are kept as separate records",
        ),
        advances=(
            AdvanceSpec("LA-1", "FARMER-2", Decimal("50000.00"), WEEK_1[0]),
            AdvanceSpec("LA-2", "FARMER-2", Decimal("5000.00"), WEEK_1[0]),
        ),
        deliveries=(
            DeliverySpec(
                "LA-D1",
                "FARMER-2",
                "MAIZE",
                "B",
                date(2026, 1, 7),
                Decimal("200.000"),
                Decimal("14.00"),
            ),
        ),
    ),
    Scenario(
        key="finalised-and-corrections",
        description="WEEK_1 is finalised/paid; correction notes are recorded "
        "later against a WEEK_1 delivery.",
        expected=(
            (
                "Correction accounting_date (not the original delivered_on) selects "
                "the payout week."
            ),
            (
                "A credit note dated WEEK_2 adds to the next eligible payout; if the "
                "target week is already finalised, a supplementary payout is used."
            ),
        ),
        deliveries=(
            DeliverySpec(
                "FC-ORIGINAL",
                "FARMER-1",
                "MAIZE",
                "A",
                WEEK_1[0],
                Decimal("100.000"),
                Decimal("14.00"),
            ),
        ),
        corrections=(
            CorrectionSpec(
                "FC-CREDIT",
                "FC-ORIGINAL",
                "CREDIT_NOTE",
                Decimal("75.00"),
                date(2026, 1, 13),
                "Moisture re-measured downwards",
            ),
            CorrectionSpec(
                "FC-DEBIT",
                "FC-ORIGINAL",
                "DEBIT_NOTE",
                Decimal("40.00"),
                date(2026, 1, 14),
                "Rate applied was too high",
            ),
        ),
    ),
)
