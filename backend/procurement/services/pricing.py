"""Effective-dated price history.

Assignment rule: a delivery is priced with the latest :class:`PriceListEntry`
whose ``effective_from`` is on or before the delivery date. Price history is
**append-only**: :func:`resolve_price` only reads, and :func:`create_price_entry`
only adds new entries -- the service exposes no update or delete path, so an
existing entry (and any delivery snapshot that froze it) is never rewritten.

Duplicate-effective-date policy
-------------------------------
``PriceListEntry`` carries the unique constraint ``pricelist_grade_eff_unique``
on ``(crop_grade, effective_from)``. The same (grade, effective date) is never
re-priced: a second entry for that pair is rejected up front with
:class:`PriceAlreadyExists`, and a database uniqueness conflict (e.g. a
concurrent insert that slips past the pre-check) is converted to the same error
so callers see one consistent outcome.
"""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from procurement.models import Crop, CropGrade, PriceListEntry
from procurement.precision import MONEY_PLACES, quantize, validate_precision

from .errors import GradeNotAllowed, PriceAlreadyExists, PriceNotFound
from .validation import as_decimal

__all__ = [
    "GradeNotAllowed",
    "PriceAlreadyExists",
    "PriceNotFound",
    "create_price_entry",
    "resolve_price",
]


def resolve_price(crop_grade: CropGrade, on_date: date) -> PriceListEntry:
    """Return the price effective on or before ``on_date`` for ``crop_grade``.

    Considers only entries whose ``effective_from`` is on or before ``on_date``
    (so an entry effective exactly on ``on_date`` is included and a
    future-effective price is excluded), and returns the latest of those. Ties on
    ``effective_from`` are broken by ``pk`` for determinism.

    Raises :class:`PriceNotFound` -- naming the missing crop and grade -- when no
    eligible entry exists.
    """
    entry = (
        PriceListEntry.objects.filter(
            crop_grade=crop_grade, effective_from__lte=on_date
        )
        .order_by("-effective_from", "-pk")
        .first()
    )
    if entry is None:
        raise PriceNotFound(
            f"No price for crop '{crop_grade.crop.name}' grade "
            f"'{crop_grade.code}' effective on or before {on_date}."
        )
    return entry


def _resolve_allowed_grade(crop: Crop, grade: CropGrade | str) -> CropGrade:
    """Return the ``CropGrade`` for ``crop``, rejecting a disallowed grade.

    ``grade`` may be an existing :class:`CropGrade` (which must belong to
    ``crop``) or a grade code (which must exist under ``crop``). Either way the
    crop/grade relationship is validated before any price is written.
    """
    if isinstance(grade, CropGrade):
        if grade.crop_id != crop.pk:
            raise GradeNotAllowed(
                f"Grade '{grade.code}' belongs to crop "
                f"'{grade.crop.name}', not '{crop.name}'."
            )
        return grade

    code = str(grade)
    resolved = CropGrade.objects.filter(crop=crop, code=code).first()
    if resolved is None:
        raise GradeNotAllowed(
            f"Grade '{code}' is not allowed for crop '{crop.name}'."
        )
    return resolved


def _already_priced(crop_grade: CropGrade, effective_from: date) -> bool:
    """Return whether ``(grade, effective_from)`` is already priced."""
    return PriceListEntry.objects.filter(
        crop_grade=crop_grade, effective_from=effective_from
    ).exists()


def create_price_entry(
    crop: Crop,
    grade: CropGrade | str,
    price_per_kg,
    effective_from: date,
) -> PriceListEntry:
    """Append a price entry for ``crop``/``grade`` effective from a date.

    Append-only: creates a new immutable history row. Back-dated effective dates
    are allowed and never rewrite existing entries or frozen delivery snapshots.

    Rejects an over-precise or non-positive rate with ``ValidationError``, a
    grade that is not allowed for the crop with :class:`GradeNotAllowed`, and a
    duplicate ``(grade, effective_from)`` -- whether detected up front or by the
    database unique constraint -- with :class:`PriceAlreadyExists`.
    """
    value = as_decimal(price_per_kg, "price_per_kg")
    validate_precision(value, MONEY_PLACES, "price_per_kg")
    if value <= 0:
        raise ValidationError(
            "price_per_kg must be greater than zero.", code="not_positive"
        )
    if effective_from is None:
        raise ValidationError("effective_from is required.", code="required")

    crop_grade = _resolve_allowed_grade(crop, grade)
    price = quantize(value, MONEY_PLACES)

    with transaction.atomic():
        if _already_priced(crop_grade, effective_from):
            raise PriceAlreadyExists(
                f"A price for crop '{crop.name}' grade '{crop_grade.code}' "
                f"effective {effective_from} already exists."
            )
        try:
            return PriceListEntry.objects.create(
                crop_grade=crop_grade,
                price_per_kg=price,
                effective_from=effective_from,
            )
        except IntegrityError as exc:
            raise PriceAlreadyExists(
                f"A price for crop '{crop.name}' grade '{crop_grade.code}' "
                f"effective {effective_from} already exists."
            ) from exc
