"""Canonical numeric precision contract for HarvestLedger.

Values are supplied at a documented precision and are **rejected**, never
silently rounded, when they carry more decimal places than allowed. Deliberate
rounding happens only inside the calculation logic, using ``Decimal`` with
``ROUND_HALF_UP``. Binary floating point (``float``) is never used for weights,
moisture, prices or money.

Precision and ranges
--------------------
===========================  ========  =====================  ==============================
Quantity                     Places    max_digits/places      Supported range
===========================  ========  =====================  ==============================
``gross_weight_kg``          3         ``12/3``               0.001 .. 999,999,999.999 kg
``moisture_percent``         2         ``5/2``                0.00 .. 999.99 (<= 100 by rule)
``threshold_used``           2         ``5/2``                0.00 .. 999.99 (<= 100 by rule)
``deduction_percent``        2         ``5/2``                0.00 .. 100.00
``deduction_kg``/``net_kg``  5         ``15/5``               0.00000 .. 9,999,999,999.99999 kg
``price_per_kg``             2         ``12/2``               0.01 .. 9,999,999,999.99
``applied_price``            2         ``12/2``               0.00 .. 9,999,999,999.99
money (amounts/balances)     2         ``14/2``               0.00 .. 999,999,999,999.99
===========================  ========  =====================  ==============================

Where excess input precision is rejected (and where it is not)
--------------------------------------------------------------
1. **M1 model/input validation.** Every ``DecimalField`` declares ``max_digits``
   and ``decimal_places``; Django attaches a ``DecimalValidator`` to each one and
   runs it from ``Model.full_clean()`` and therefore from ModelForms and the
   admin. That is the M1 gate. ``save()`` does **not** call ``full_clean()``, so
   direct writes (``save()``, ``bulk_create()``, ``QuerySet.update()``, raw SQL)
   bypass it.
2. **M2 service entry points.** Service functions call
   :func:`validate_precision` on raw input *before* calculating or writing, then
   perform ``Decimal`` / ``ROUND_HALF_UP`` arithmetic (see :func:`quantize`).
   This is the authoritative enforcement, because it covers the direct-write
   paths the model layer cannot.
3. **M3 serializer validation.** DRF ``DecimalField`` is declared with the same
   ``max_digits``/``decimal_places`` and ``rounding=None`` so excess precision is
   rejected at the API boundary before it reaches services.

Do not rely on ``DecimalField`` alone: it does not protect writes that skip
``full_clean()``.
"""

import decimal
from decimal import Decimal

from django.core.exceptions import ValidationError

GROSS_KG_PLACES = 3
MOISTURE_PLACES = 2
DERIVED_KG_PLACES = 5
MONEY_PLACES = 2

ROUNDING = decimal.ROUND_HALF_UP

MONEY_QUANTUM = Decimal("0.01")
DERIVED_KG_QUANTUM = Decimal("0.00001")
GROSS_KG_QUANTUM = Decimal("0.001")
MOISTURE_QUANTUM = Decimal("0.01")


def decimal_places(value: Decimal) -> int:
    """Return the number of decimal places a finite ``Decimal`` is expressed with.

    Trailing zeros count: ``Decimal("1.2300")`` is 4 places, not 2.
    """
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def validate_precision(value, places: int, field_name: str = "value") -> None:
    """Reject ``value`` when it carries more than ``places`` decimal places.

    Shared by M2 service entry points and available to M3 serializers. ``None``
    is ignored so optional fields can be validated in the same pass.
    """
    if value is None:
        return
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except (decimal.InvalidOperation, ValueError, TypeError) as exc:
            raise ValidationError(
                f"{field_name} must be a decimal number.",
                code="invalid_decimal",
            ) from exc
    if not value.is_finite():
        raise ValidationError(
            f"{field_name} must be a finite decimal number.",
            code="invalid_decimal",
        )
    found = decimal_places(value)
    if found > places:
        raise ValidationError(
            f"{field_name} must have at most {places} decimal place(s), got {found}.",
            code="too_many_decimal_places",
        )


def quantize(value, places: int) -> Decimal:
    """Return ``value`` rounded to ``places`` decimal places using ROUND_HALF_UP.

    The single rounding primitive; the M2 delivery engine builds on it. Not used
    to *accept* over-precise input -- input is rejected before this is reached.
    """
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUNDING)
