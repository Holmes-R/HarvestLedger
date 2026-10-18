"""Input coercion shared by the M2 service entry points.

Only converts non-``Decimal`` input; floats would be converted via ``str`` to
avoid binary-float artefacts, but callers are expected to pass ``Decimal``.
Precision is still enforced afterwards by :func:`procurement.precision.validate_precision`.
"""

import decimal
from decimal import Decimal

from django.core.exceptions import ValidationError


def as_decimal(value, field_name: str = "value") -> Decimal:
    """Return ``value`` as a ``Decimal`` or raise ``ValidationError``."""
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (decimal.InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError(
            f"{field_name} must be a decimal number.",
            code="invalid_decimal",
        ) from exc
