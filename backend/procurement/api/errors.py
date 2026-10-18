"""Uniform API error contract for the M3 HTTP layer.

The API never re-implements business rules. The service layer raises
:class:`~procurement.services.errors.ServiceError` (domain rules) or Django
``ValidationError`` (field/input); this module maps their stable ``code`` to an
HTTP status and one response shape::

    {"error": {"code": "...", "message": "...", "fields": {...} | null}}

Unexpected exceptions become a generic ``500`` with no traceback or credential
content: only the exception class name and a correlation reference are logged.
"""

import logging
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from procurement.services.errors import ServiceError

logger = logging.getLogger("procurement.api")


class EmptyWeek(APIException):
    """No deliveries fall in the requested week (documented service sentinel).

    ``payouts.build_weekly_payout`` returns ``None`` for an empty week; the API
    surfaces that as ``409`` so the client can distinguish it from a bad request.
    """

    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "No deliveries fall in that week; there is no payout to generate."
    )
    default_code = "empty_week"

#: Explicit code -> HTTP status overrides. Anything unlisted falls back per type:
#: ``ValidationError`` -> 400, ``ServiceError`` -> 422.
_CODE_STATUS = {
    # Referenced object absent (or resolved-not-found by a view).
    "farmer_not_found": status.HTTP_404_NOT_FOUND,
    "crop_not_found": status.HTTP_404_NOT_FOUND,
    "crop_grade_not_found": status.HTTP_404_NOT_FOUND,
    "original_not_found": status.HTTP_404_NOT_FOUND,
    "not_found": status.HTTP_404_NOT_FOUND,
    # Conflicts / invalid state transitions.
    "payout_state_error": status.HTTP_409_CONFLICT,
    "price_already_exists": status.HTTP_409_CONFLICT,
    "original_not_settled": status.HTTP_409_CONFLICT,
    "original_changed": status.HTTP_409_CONFLICT,
    "not_editable": status.HTTP_409_CONFLICT,
    "advance_reconciliation_failed": status.HTTP_409_CONFLICT,
    # Well-formed request rejected by a domain rule.
    "price_not_found": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "grade_not_allowed": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "moisture_exceeds_maximum": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "future_delivery_date": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "invalid_moisture_bounds": status.HTTP_422_UNPROCESSABLE_ENTITY,
}

_FALLBACK_VALIDATION = status.HTTP_400_BAD_REQUEST
_FALLBACK_SERVICE = status.HTTP_422_UNPROCESSABLE_ENTITY


def _status_for(code, fallback):
    return _CODE_STATUS.get(code, fallback)


def _envelope(code, message, fields=None, reference=None):
    error = {
        "code": code or "error",
        "message": message or "",
        "fields": fields,
    }
    if reference is not None:
        error["reference"] = reference
    return {"error": error}


def _django_validation(exc):
    """Return ``(fields, message, code)`` for a Django ``ValidationError``."""
    fields = {}
    messages = []
    codes = []
    if hasattr(exc, "error_dict"):
        for name, errors in exc.error_dict.items():
            items = []
            for error in errors:
                codes.append(getattr(error, "code", None))
                messages.append(str(error.message))
                items.append(
                    {"code": getattr(error, "code", None), "message": str(error.message)}
                )
            fields[name] = items
    else:
        for error in exc.error_list:
            codes.append(getattr(error, "code", None))
            messages.append(str(error.message))
    code = next((c for c in codes if c), None)
    return (fields or None), "; ".join(messages), code


def _flatten(detail):
    if isinstance(detail, dict):
        return "; ".join(_flatten(value) for value in detail.values())
    if isinstance(detail, (list, tuple)):
        return "; ".join(_flatten(value) for value in detail)
    return str(detail)


def _drf_validation(exc):
    """Return ``(fields, message, code)`` for a DRF ``ValidationError``."""
    detail = exc.detail
    fields = {}
    codes = []
    if isinstance(detail, dict):
        for name, value in detail.items():
            entries = value if isinstance(value, (list, tuple)) else [value]
            items = []
            for entry in entries:
                code = getattr(entry, "code", None)
                codes.append(code)
                items.append({"code": code, "message": str(entry)})
            fields[name] = items
    elif isinstance(detail, (list, tuple)):
        for entry in detail:
            codes.append(getattr(entry, "code", None))
    else:
        codes.append(getattr(detail, "code", None))
    code = next((c for c in codes if c), None)
    return (fields or None), _flatten(detail), code


def _wrap_drf_response(response):
    """Force a default DRF error response into the unified envelope."""
    data = response.data
    if isinstance(data, dict) and "error" in data:
        return response
    if isinstance(data, dict) and "detail" in data:
        detail = data["detail"]
        code = getattr(detail, "code", None)
        if not code and response.status_code == status.HTTP_404_NOT_FOUND:
            code = "not_found"
        message = str(detail)
        fields = None
    elif isinstance(data, dict):
        code, message, fields = "invalid", "Request validation failed.", data
    else:
        code, message, fields = "error", str(data), None
    response.data = _envelope(code, message, fields)
    return response


def api_exception_handler(exc, context):
    """DRF exception handler implementing the contract above."""
    if isinstance(exc, ServiceError):
        code = exc.code
        return Response(
            _envelope(code, exc.message),
            status=_status_for(code, _FALLBACK_SERVICE),
        )

    if isinstance(exc, DRFValidationError):
        fields, message, code = _drf_validation(exc)
        return Response(
            _envelope(code, message, fields),
            status=_status_for(code, _FALLBACK_VALIDATION),
        )

    if isinstance(exc, DjangoValidationError):
        fields, message, code = _django_validation(exc)
        return Response(
            _envelope(code, message, fields),
            status=_status_for(code, _FALLBACK_VALIDATION),
        )

    response = drf_exception_handler(exc, context)
    if response is not None:
        return _wrap_drf_response(response)

    reference = uuid.uuid4().hex
    logger.error("Unhandled API error [%s]: %s", reference, type(exc).__name__)
    return Response(
        _envelope("internal_error", "An unexpected error occurred.", None, reference),
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
