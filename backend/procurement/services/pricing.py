"""Effective-dated price resolution.

Assignment rule: a delivery is priced with the latest :class:`PriceListEntry`
whose ``effective_from`` is on or before the delivery date. Prices are immutable
history; this function only reads.
"""

from datetime import date

from procurement.models import CropGrade, PriceListEntry

from .errors import PriceNotFound

__all__ = ["PriceNotFound", "resolve_price"]


def resolve_price(crop_grade: CropGrade, on_date: date) -> PriceListEntry:
    """Return the price effective on or before ``on_date`` for ``crop_grade``.

    Raises :class:`PriceNotFound` when no entry is eligible. Ties on
    ``effective_from`` are broken by ``pk`` for determinism.
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
            f"No price for {crop_grade} effective on or before {on_date}."
        )
    return entry
