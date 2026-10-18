"""Seed deterministic demo data.

``python manage.py seed_data`` writes a fixed demo dataset:

* reference data -- crops (with moisture thresholds), allowed grade codes,
  invented demo farmers (format-valid example mobile numbers) and
  effective-dated price entries;
* a small **financial** history built **through the M2 service layer** --
  advances, deliveries, weekly payouts (draft, finalised and paid), a
  correction note and a supplementary payout.

Coverage (see :mod:`procurement.scenarios` for the declarative manifest)
-----------------------------------------------------------------------
* multiple Monday..Sunday weeks,
* moisture boundaries (below / at / fractional / near max),
* effective-date price selection (an older rate is used for a backdated
  delivery),
* a missing-rate example -- probed through ``record_delivery`` and *not*
  persisted (the ``PriceNotFound`` is expected and swallowed),
* a large advance carried across successive payouts (recovery cap + remainder),
* a finalised/paid delivery with a later correction note, and
* a supplementary payout for a week that was already settled.

Guarantees
----------
* **Deterministic** -- every value is hard-coded; no randomness. Transactions are
  written through the services with a frozen business clock so dates are fixed.
* **Stable demo identifiers** -- every transaction has a stable ``key``; see the
  natural-key notes below.
* **Atomic** -- the whole run is one transaction; any failure rolls back
  reference *and* financial rows together.
* **Repeatable** -- each transaction is guarded by its natural key, so a second
  run creates nothing, reapplies no recovery and leaves balances untouched.
* **Non-destructive** -- existing rows (including frozen snapshots, payout
  statements and the outstanding balance) are never updated, reset or rewritten.

Natural keys used for idempotency
---------------------------------
* ``Crop``            -> ``name``
* ``CropGrade``       -> ``(crop, code)``
* ``PriceListEntry``  -> ``(crop_grade, effective_from)``
* ``Farmer``          -> ``phone``
* ``Advance``         -> ``(farmer, given_on, amount)`` -- the amount is part of
  the key, so same-day advances are **not** deduplicated by farmer/date alone.
* ``PROCUREMENT`` delivery -> ``(farmer, crop_grade, delivered_on, gross_weight_kg,
  moisture_percent)`` (its recorded inputs)
* correction note     -> ``(original_delivery, kind, correction_magnitude, reason,
  accounting_date)``
* ``Payout``          -> the delivery/note it was generated for (a payout is
  reused when its anchor record is already assigned)

Advance deduplication warning
-----------------------------
Multiple advances may legitimately be issued to one farmer on the same date.
``(farmer, given_on)`` must therefore **not** be used as an advance
deduplication key. See ``ADVANCE_DEDUPLICATION_NOTE`` in
:mod:`procurement.scenarios`.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from procurement.clock import FrozenClock
from procurement.models import (
    Advance,
    Crop,
    CropGrade,
    Delivery,
    DeliveryKind,
    Farmer,
    Payout,
    PayoutStatus,
    PriceListEntry,
)
from procurement.services import advances, corrections, delivery, payouts, pricing


@dataclass(frozen=True)
class CropSpec:
    key: str
    name: str
    moisture_threshold: Decimal
    max_moisture: Decimal
    grades: tuple[str, ...]


@dataclass(frozen=True)
class PriceSpec:
    crop_key: str
    grade_code: str
    price_per_kg: Decimal
    effective_from: date


@dataclass(frozen=True)
class FarmerSpec:
    key: str
    name: str
    phone: str
    village: str


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
    original_key: str
    kind: str
    magnitude: Decimal
    reason: str
    accounting_date: date


@dataclass(frozen=True)
class MissingRateSpec:
    key: str
    farmer_key: str
    crop_key: str
    grade_code: str
    delivered_on: date
    gross_weight_kg: Decimal
    moisture_percent: Decimal


@dataclass(frozen=True)
class PayoutSpec:
    key: str
    farmer_key: str
    week_start: date
    anchor_key: str
    finalise: bool
    pay: bool


DEMO_CROPS: tuple[CropSpec, ...] = (
    CropSpec(
        key="MAIZE",
        name="Maize",
        moisture_threshold=Decimal("14.00"),
        max_moisture=Decimal("20.00"),
        grades=("A", "B"),
    ),
    CropSpec(
        key="PADDY",
        name="Paddy",
        moisture_threshold=Decimal("12.00"),
        max_moisture=Decimal("18.00"),
        grades=("A", "B"),
    ),
    CropSpec(
        key="GROUNDNUT",
        name="Groundnut",
        moisture_threshold=Decimal("08.00"),
        max_moisture=Decimal("12.00"),
        grades=("A",),
    ),
)


# Historical, effective-dated rates. Effective dates are stable; the same
# (grade, effective_from) is never re-priced, so re-running never rewrites
# history. Prices intentionally include several historical points so the
# effective-date selection can be demonstrated.
DEMO_PRICES: tuple[PriceSpec, ...] = (
    PriceSpec("MAIZE", "A", Decimal("22.00"), date(2025, 11, 1)),
    PriceSpec("MAIZE", "A", Decimal("24.50"), date(2026, 1, 1)),
    PriceSpec("MAIZE", "A", Decimal("25.75"), date(2026, 4, 1)),
    PriceSpec("MAIZE", "B", Decimal("19.00"), date(2025, 11, 1)),
    PriceSpec("MAIZE", "B", Decimal("21.00"), date(2026, 1, 1)),
    PriceSpec("PADDY", "A", Decimal("26.00"), date(2025, 11, 1)),
    PriceSpec("PADDY", "A", Decimal("27.50"), date(2026, 1, 1)),
    PriceSpec("PADDY", "B", Decimal("23.00"), date(2026, 1, 1)),
    PriceSpec("GROUNDNUT", "A", Decimal("58.00"), date(2025, 11, 1)),
    PriceSpec("GROUNDNUT", "A", Decimal("61.25"), date(2026, 1, 1)),
)


# Fictional farmers with format-valid example mobile numbers used as stable
# demo identifiers. They are not verified contact numbers. bank_reference is
# intentionally empty: no real banking information.
DEMO_FARMERS: tuple[FarmerSpec, ...] = (
    FarmerSpec("FARMER-1", "Aarti Bhosale", "9000000001", "Kolar"),
    FarmerSpec("FARMER-2", "Ganesh Pillai", "9000000002", "Mandya"),
    FarmerSpec("FARMER-3", "Meera Nair", "9000000003", "Mandya"),
)


# --- Financial demo (executed through procurement.services) ----------------

# Two advances to FARMER-2 on the same date (50000 + 5000 = 55000 outstanding)
# prove that (farmer, given_on) is not a deduplication key; the recovery cap
# carries the remainder across successive weeks.
DEMO_ADVANCES: tuple[AdvanceSpec, ...] = (
    AdvanceSpec("ADV-F1", "FARMER-1", Decimal("1000.00"), date(2026, 1, 5)),
    AdvanceSpec("ADV-F2-A", "FARMER-2", Decimal("50000.00"), date(2026, 1, 5)),
    AdvanceSpec("ADV-F2-B", "FARMER-2", Decimal("5000.00"), date(2026, 1, 5)),
)


DEMO_DELIVERIES: tuple[DeliverySpec, ...] = (
    # Backdated delivery: only the 2025-11-01 rate (22.00) is effective, so the
    # effective-date selection picks it over the later 2026-01-01 rate.
    DeliverySpec(
        "D-BACKDATED",
        "FARMER-1",
        "MAIZE",
        "A",
        date(2025, 12, 20),
        Decimal("100.000"),
        Decimal("14.00"),
    ),
    # WEEK 1 (2026-01-05..11): moisture boundary set (threshold 14.00, max 20.00).
    DeliverySpec(
        "D-W1-AT",
        "FARMER-1",
        "MAIZE",
        "A",
        date(2026, 1, 6),
        Decimal("100.000"),
        Decimal("14.00"),
    ),
    DeliverySpec(
        "D-W1-BELOW",
        "FARMER-1",
        "MAIZE",
        "A",
        date(2026, 1, 6),
        Decimal("100.000"),
        Decimal("13.00"),
    ),
    DeliverySpec(
        "D-W1-FRACTION",
        "FARMER-1",
        "MAIZE",
        "A",
        date(2026, 1, 7),
        Decimal("100.000"),
        Decimal("15.99"),
    ),
    DeliverySpec(
        "D-W1-NEAR-MAX",
        "FARMER-1",
        "MAIZE",
        "A",
        date(2026, 1, 8),
        Decimal("100.000"),
        Decimal("19.99"),
    ),
    # WEEK 2 / WEEK 3.
    DeliverySpec(
        "D-W2",
        "FARMER-1",
        "MAIZE",
        "A",
        date(2026, 1, 13),
        Decimal("80.500"),
        Decimal("14.00"),
    ),
    DeliverySpec(
        "D-W3",
        "FARMER-1",
        "MAIZE",
        "A",
        date(2026, 1, 20),
        Decimal("60.250"),
        Decimal("14.00"),
    ),
    # FARMER-2 across two weeks, to carry the large advance forward.
    DeliverySpec(
        "D-F2-W1",
        "FARMER-2",
        "MAIZE",
        "B",
        date(2026, 1, 7),
        Decimal("200.000"),
        Decimal("14.00"),
    ),
    DeliverySpec(
        "D-F2-W2",
        "FARMER-2",
        "MAIZE",
        "B",
        date(2026, 1, 13),
        Decimal("200.000"),
        Decimal("14.00"),
    ),
)


# Missing rate: Groundnut A has no entry effective before 2025-11-01, so a
# delivery this early raises PriceNotFound. It is probed (expected to fail) and
# never persisted.
DEMO_MISSING_RATE: MissingRateSpec = MissingRateSpec(
    "MR-GROUNDNUT",
    "FARMER-3",
    "GROUNDNUT",
    "A",
    date(2025, 10, 15),
    Decimal("100.000"),
    Decimal("12.00"),
)


# A credit note recorded *after* WEEK 1 is finalised/paid; its accounting date
# (2026-01-08) is inside WEEK 1, so it needs a supplementary payout for that
# already-settled week.
DEMO_CORRECTIONS: tuple[CorrectionSpec, ...] = (
    CorrectionSpec(
        "CORR-W1-CREDIT",
        "D-W1-AT",
        DeliveryKind.CREDIT_NOTE,
        Decimal("75.00"),
        "Moisture re-measured downwards",
        date(2026, 1, 8),
    ),
)


# Payout actions, in execution order. The correction-anchored supplementary is
# listed after the WEEK 1 payouts so the original is already finalised/paid.
DEMO_PAYOUTS: tuple[PayoutSpec, ...] = (
    PayoutSpec("P-BACKDATED", "FARMER-1", date(2025, 12, 15), "D-BACKDATED", True, False),
    PayoutSpec("P-W1-F1", "FARMER-1", date(2026, 1, 5), "D-W1-AT", True, True),
    PayoutSpec("P-W1-F2", "FARMER-2", date(2026, 1, 5), "D-F2-W1", True, True),
    PayoutSpec("P-W2-F1", "FARMER-1", date(2026, 1, 12), "D-W2", True, False),
    PayoutSpec("P-W2-F2", "FARMER-2", date(2026, 1, 12), "D-F2-W2", True, False),
    PayoutSpec(
        "P-W1-F1-SUP", "FARMER-1", date(2026, 1, 5), "CORR-W1-CREDIT", False, False
    ),
    PayoutSpec("P-W3-F1", "FARMER-1", date(2026, 1, 19), "D-W3", False, False),
)


def _business_instant(business_day: date) -> datetime:
    """06:00 UTC == 11:30 IST, so the IST business date equals ``business_day``."""
    return datetime(
        business_day.year, business_day.month, business_day.day, 6, 0, tzinfo=UTC
    )


def _frozen(business_day: date) -> FrozenClock:
    return FrozenClock(_business_instant(business_day))


class Command(BaseCommand):
    help = (
        "Seed deterministic demo data (reference data plus a service-built "
        "financial history)."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        stats: dict[str, list[int]] = {
            "Crop": [0, 0],
            "CropGrade": [0, 0],
            "Farmer": [0, 0],
            "PriceListEntry": [0, 0],
            "Advance": [0, 0],
            "Delivery": [0, 0],
            "Correction": [0, 0],
            "Payout": [0, 0],
        }

        crops: dict[str, Crop] = {}
        for spec in DEMO_CROPS:
            crop, created = Crop.objects.get_or_create(
                name=spec.name,
                defaults={
                    "moisture_threshold": spec.moisture_threshold,
                    "max_moisture": spec.max_moisture,
                },
            )
            crops[spec.key] = crop
            stats["Crop"][0 if created else 1] += 1

        grades: dict[tuple[str, str], CropGrade] = {}
        for spec in DEMO_CROPS:
            for code in spec.grades:
                grade, created = CropGrade.objects.get_or_create(
                    crop=crops[spec.key], code=code
                )
                grades[(spec.key, code)] = grade
                stats["CropGrade"][0 if created else 1] += 1

        for spec in DEMO_PRICES:
            _, created = PriceListEntry.objects.get_or_create(
                crop_grade=grades[(spec.crop_key, spec.grade_code)],
                effective_from=spec.effective_from,
                defaults={"price_per_kg": spec.price_per_kg},
            )
            stats["PriceListEntry"][0 if created else 1] += 1

        farmers: dict[str, Farmer] = {}
        for spec in DEMO_FARMERS:
            farmer, created = Farmer.objects.get_or_create(
                phone=spec.phone,
                defaults={
                    "name": spec.name,
                    "village": spec.village,
                    "outstanding_advance": Decimal(0),
                },
            )
            farmers[spec.key] = farmer
            stats["Farmer"][0 if created else 1] += 1

        self._seed_financials(stats, grades, farmers)

        self.stdout.write("Seeded demo data (idempotent, deterministic):")
        for label, (created, existing) in stats.items():
            self.stdout.write(f"  {label}: {created} created, {existing} existing")
        self.stdout.write(
            self.style.SUCCESS(
                "Done. Financial history was built through procurement.services "
                "(no recovery was reapplied and no balance was reset)."
            )
        )

    # -- financial demo -----------------------------------------------------

    def _seed_financials(
        self,
        stats: dict[str, list[int]],
        grades: dict[tuple[str, str], CropGrade],
        farmers: dict[str, Farmer],
    ) -> None:
        deliveries: dict[str, Delivery] = {}
        corrections: dict[str, Delivery] = {}

        for spec in DEMO_ADVANCES:
            farmer = farmers[spec.farmer_key]
            existing = Advance.objects.filter(
                farmer=farmer, given_on=spec.given_on, amount=spec.amount
            ).exists()
            if existing:
                stats["Advance"][1] += 1
                continue
            advances.post_advance(farmer, spec.amount, spec.given_on)
            stats["Advance"][0] += 1

        for spec in DEMO_DELIVERIES:
            deliveries[spec.key] = self._ensure_delivery(spec, grades, farmers, stats)

        self._probe_missing_rate(grades, farmers)

        for plan in DEMO_PAYOUTS:
            farmer = farmers[plan.farmer_key]
            anchor = self._anchor(plan.anchor_key, deliveries, corrections, stats)
            anchor.refresh_from_db(fields=["payout"])
            if anchor.payout_id is None:
                payout = payouts.build_weekly_payout(farmer, plan.week_start)
                stats["Payout"][0] += 1
            else:
                payout = Payout.objects.get(pk=anchor.payout_id)
                stats["Payout"][1] += 1

            if plan.finalise and payout.status == PayoutStatus.DRAFT:
                payout = payouts.finalise_payout(payout)
            if plan.pay and payout.status == PayoutStatus.FINALISED:
                payouts.mark_payout_paid(payout)

    def _anchor(
        self,
        key: str,
        deliveries: dict[str, Delivery],
        corrections: dict[str, Delivery],
        stats: dict[str, list[int]],
    ) -> Delivery:
        if key in deliveries:
            return deliveries[key]
        if key in corrections:
            return corrections[key]
        spec = next(c for c in DEMO_CORRECTIONS if c.key == key)
        original = deliveries[spec.original_key]
        # The payout assignment happened through other objects, so reload the
        # original (and its payout relation) before the correction reads them.
        original.refresh_from_db()
        note = self._ensure_correction(spec, original, stats)
        corrections[spec.key] = note
        return note

    def _ensure_delivery(
        self,
        spec: DeliverySpec,
        grades: dict[tuple[str, str], CropGrade],
        farmers: dict[str, Farmer],
        stats: dict[str, list[int]],
    ) -> Delivery:
        farmer = farmers[spec.farmer_key]
        grade = grades[(spec.crop_key, spec.grade_code)]
        existing = Delivery.objects.filter(
            farmer=farmer,
            kind=DeliveryKind.PROCUREMENT,
            crop_grade=grade,
            delivered_on=spec.delivered_on,
            gross_weight_kg=spec.gross_weight_kg,
            moisture_percent=spec.moisture_percent,
        ).first()
        if existing is not None:
            stats["Delivery"][1] += 1
            return existing
        row = delivery.record_delivery(
            farmer=farmer,
            crop_grade=grade,
            delivered_on=spec.delivered_on,
            gross_weight_kg=spec.gross_weight_kg,
            moisture_percent=spec.moisture_percent,
            clock=_frozen(spec.delivered_on),
        )
        stats["Delivery"][0] += 1
        return row

    def _ensure_correction(
        self,
        spec: CorrectionSpec,
        original: Delivery,
        stats: dict[str, list[int]],
    ) -> Delivery:
        existing = Delivery.objects.filter(
            original_delivery=original,
            kind=spec.kind,
            correction_magnitude=spec.magnitude,
            reason=spec.reason,
            accounting_date=spec.accounting_date,
        ).first()
        if existing is not None:
            stats["Correction"][1] += 1
            return existing
        note = corrections.record_correction(
            original_delivery=original,
            kind=spec.kind,
            magnitude=spec.magnitude,
            reason=spec.reason,
            clock=_frozen(spec.accounting_date),
        )
        stats["Correction"][0] += 1
        return note

    def _probe_missing_rate(
        self,
        grades: dict[tuple[str, str], CropGrade],
        farmers: dict[str, Farmer],
    ) -> None:
        """Exercise the missing-rate path without persisting an invalid delivery."""
        spec = DEMO_MISSING_RATE
        if Delivery.objects.filter(
            farmer=farmers[spec.farmer_key],
            kind=DeliveryKind.PROCUREMENT,
            delivered_on=spec.delivered_on,
        ).exists():
            return
        try:
            delivery.record_delivery(
                farmer=farmers[spec.farmer_key],
                crop_grade=grades[(spec.crop_key, spec.grade_code)],
                delivered_on=spec.delivered_on,
                gross_weight_kg=spec.gross_weight_kg,
                moisture_percent=spec.moisture_percent,
                clock=_frozen(spec.delivered_on),
            )
        except pricing.PriceNotFound:
            return
        raise AssertionError(
            "demo missing-rate delivery unexpectedly resolved a price"
        )
