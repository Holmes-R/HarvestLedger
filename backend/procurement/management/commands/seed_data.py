"""Seed deterministic M1 reference data.

``python manage.py seed_data`` writes **reference data only**:

* crops (with their moisture thresholds),
* allowed grade codes per crop,
* invented demo farmers (zero outstanding advance),
* effective-dated price entries.

It never touches financial records. Advances, deliveries and payouts require
the M2 service layer, so the seed command deliberately creates none -- see
:mod:`procurement.scenarios` for the M2 scenario manifest.

Guarantees
----------
* **Deterministic** -- every value is hard-coded; no randomness, no clock reads.
* **Stable demo identifiers** -- each row has a stable ``key``. The natural keys
  used for idempotency are documented in ``Natural key`` notes below.
* **Atomic** -- the whole run is one transaction; any failure rolls back.
* **Repeatable** -- ``get_or_create`` means re-running adds nothing and reports
  the rows as *existing*.
* **Non-destructive** -- existing rows are never updated, cleared or reset, so
  historical prices, frozen snapshots and (future) balances are preserved.
* **Synthetic** -- names and example mobile numbers are invented; there is no
  verified farmer or banking data (``bank_reference`` is left blank).

Natural keys used for idempotency
---------------------------------
* ``Crop``            -> ``name``
* ``CropGrade``       -> ``(crop, code)``
* ``PriceListEntry``  -> ``(crop_grade, effective_from)``
* ``Farmer``          -> ``phone`` (a stable example number used as the demo
  identifier)

Advance deduplication warning (for M2)
--------------------------------------
Multiple advances may legitimately be issued to one farmer on the same date.
``(farmer, given_on)`` must therefore **not** be used as an advance
deduplication key. See ``ADVANCE_DEDUPLICATION_NOTE`` in
:mod:`procurement.scenarios`.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from procurement.models import Crop, CropGrade, Farmer, PriceListEntry


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
# history. Prices intentionally include several historical points so M2 can
# resolve "the latest price effective on or before delivered_on".
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


class Command(BaseCommand):
    help = "Seed deterministic M1 reference data (crops, grades, farmers, prices)."

    @transaction.atomic
    def handle(self, *args, **options):
        stats: dict[str, list[int]] = {
            "Crop": [0, 0],
            "CropGrade": [0, 0],
            "Farmer": [0, 0],
            "PriceListEntry": [0, 0],
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

        for spec in DEMO_FARMERS:
            _, created = Farmer.objects.get_or_create(
                phone=spec.phone,
                defaults={
                    "name": spec.name,
                    "village": spec.village,
                    "outstanding_advance": Decimal(0),
                },
            )
            stats["Farmer"][0 if created else 1] += 1

        self.stdout.write("Seeded M1 reference data (idempotent, deterministic):")
        for label, (created, existing) in stats.items():
            self.stdout.write(f"  {label}: {created} created, {existing} existing")
        self.stdout.write(
            self.style.SUCCESS(
                "Done. No financial records were created (advances/deliveries/"
                "payouts wait for M2 services)."
            )
        )
