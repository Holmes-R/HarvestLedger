"""Uniform API error contract for the M3 HTTP layer.

Every error uses one envelope::

    {"error": {"code": ..., "message": ..., "details": {...}, "request_id": ...}}

Codes map to HTTP statuses deliberately:

* ``400`` malformed fields, types or precision.
* ``404`` unknown resources.
* ``409`` duplicates and forbidden state transitions.
* ``422`` domain rejection (missing applicable price, excessive moisture, ...).
* ``500`` unexpected faults -- generic public message, nothing leaked.

A request ID (client-supplied when well-formed, otherwise generated) is echoed
in the body and the ``X-Request-ID`` response header and used in structured
logs. Domain rejections log at ``WARNING``; unexpected faults log at ``ERROR``
with server-side exception information. Request/response bodies, credentials,
banking references, review keys and query strings are never logged.
"""

import logging
import traceback

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from procurement.services.errors import ServiceError

from .middleware import duration_ms, record_ids
from .request_log import log_event, new_request_id

logger = logging.getLogger("procurement.api")


class GradeInUse(APIException):
    """A grade with historical usage (price or delivery) cannot be removed.

    ``409``: the request is well-formed but would destroy a grade that is
    referenced by an append-only price entry or a delivery snapshot. Existing
    history is preserved; the client must retry without that grade.
    """

    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "This grade is referenced by existing price or delivery records and "
        "cannot be removed."
    )
    default_code = "grade_in_use"


#: Explicit code -> HTTP status overrides. Anything unlisted falls back by type:
#: ``ValidationError`` -> 400, ``ServiceError`` -> 422.
_CODE_STATUS = {
    # Unknown resource.
    "farmer_not_found": status.HTTP_404_NOT_FOUND,
    "crop_not_found": status.HTTP_404_NOT_FOUND,
    "crop_grade_not_found": status.HTTP_404_NOT_FOUND,
    "original_not_found": status.HTTP_404_NOT_FOUND,
    "not_found": status.HTTP_404_NOT_FOUND,
    # Duplicates / forbidden state transitions.
    "payout_state_error": status.HTTP_409_CONFLICT,
    "price_already_exists": status.HTTP_409_CONFLICT,
    "original_not_settled": status.HTTP_409_CONFLICT,
    "original_changed": status.HTTP_409_CONFLICT,
    "not_editable": status.HTTP_409_CONFLICT,
    "advance_reconciliation_failed": status.HTTP_409_CONFLICT,
    "grade_in_use": status.HTTP_409_CONFLICT,
    "duplicate_crop": status.HTTP_409_CONFLICT,
    # Database conflicts surfaced after a rolled-back transaction.
    "duplicate_crop_grade": status.HTTP_409_CONFLICT,
    "conflict": status.HTTP_409_CONFLICT,
    "referenced_record": status.HTTP_409_CONFLICT,
    # Domain rejection of a well-formed request.
    "price_not_found": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "grade_not_allowed": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "moisture_exceeds_maximum": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "future_delivery_date": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "invalid_moisture_bounds": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "invalid_state": status.HTTP_422_UNPROCESSABLE_ENTITY,
    # Gated reviewer clock aid (see middleware.ReviewClockMiddleware).
    "review_clock_disabled": status.HTTP_403_FORBIDDEN,
    "review_clock_unauthorized": status.HTTP_403_FORBIDDEN,
    "review_clock_invalid": status.HTTP_400_BAD_REQUEST,
}

_FALLBACK_VALIDATION = status.HTTP_400_BAD_REQUEST
_FALLBACK_SERVICE = status.HTTP_422_UNPROCESSABLE_ENTITY

#: Known unique constraints -> a deliberate, specific conflict response. An
#: unknown uniqueness violation still becomes a generic 409 ``conflict``; other
#: integrity failures (NOT NULL, check, FK) are treated as server faults, never
#: misreported as conflicts.
_UNIQUE_CODES = {
    "payout_one_draft_farmer_week": (
        "payout_state_error",
        "A draft payout already exists for this farmer and week.",
    ),
    "pricelist_grade_eff_unique": (
        "price_already_exists",
        "A price entry already exists for this grade and effective date.",
    ),
    "cropgrade_unique_crop_code": (
        "duplicate_crop_grade",
        "A grade with this code already exists for the crop.",
    ),
}

_SQLSTATE_UNIQUE = "23505"
_SQLSTATE_FOREIGN_KEY = "23503"
_SQLSTATE_CHECK = "23514"


def _status_for(code, fallback):
    return _CODE_STATUS.get(code, fallback)


def _envelope(code, message, details, request_id):
    return {
        "error": {
            "code": code or "error",
            "message": message or "",
            "details": details if details else {},
            "request_id": request_id,
        }
    }


def _django_validation(exc):
    """Return ``(details, message, code)`` for a Django ``ValidationError``."""
    details = {}
    messages = []
    codes = []
    if hasattr(exc, "error_dict"):
        for name, errors in exc.error_dict.items():
            items = []
            for error in errors:
                codes.append(getattr(error, "code", None))
                messages.append(str(error.message))
                items.append(
                    {
                        "code": getattr(error, "code", None),
                        "message": str(error.message),
                    }
                )
            details[name] = items
    else:
        for error in exc.error_list:
            codes.append(getattr(error, "code", None))
            messages.append(str(error.message))
    code = next((c for c in codes if c), None)
    return details, "; ".join(messages), code


def _flatten(detail):
    if isinstance(detail, dict):
        return "; ".join(_flatten(value) for value in detail.values())
    if isinstance(detail, (list, tuple)):
        return "; ".join(_flatten(value) for value in detail)
    return str(detail)


def _drf_validation(exc):
    """Return ``(details, message, code)`` for a DRF ``ValidationError``."""
    detail = exc.detail
    details = {}
    codes = []
    if isinstance(detail, dict):
        for name, value in detail.items():
            entries = value if isinstance(value, (list, tuple)) else [value]
            items = []
            for entry in entries:
                if isinstance(entry, dict):
                    code = entry.get("code")
                    message = entry.get("message") or _flatten(entry)
                else:
                    code = getattr(entry, "code", None)
                    message = str(entry)
                codes.append(code)
                items.append({"code": code, "message": message})
            details[name] = items
    elif isinstance(detail, (list, tuple)):
        for entry in detail:
            codes.append(getattr(entry, "code", None))
    else:
        codes.append(getattr(detail, "code", None))
    code = next((c for c in codes if c), None)
    return details, _flatten(detail), code


def _database_conflict(exc):
    """Map a known post-rollback ``IntegrityError``, or ``None`` if unmapped."""
    cause = getattr(exc, "__cause__", None)
    sqlstate = getattr(cause, "sqlstate", None)
    constraint = getattr(getattr(cause, "diag", None), "constraint_name", None)
    if constraint in _UNIQUE_CODES:
        code, message = _UNIQUE_CODES[constraint]
        return code, status.HTTP_409_CONFLICT, message
    if sqlstate == _SQLSTATE_UNIQUE:
        return (
            "conflict",
            status.HTTP_409_CONFLICT,
            "A record with these values already exists.",
        )
    if sqlstate == _SQLSTATE_FOREIGN_KEY:
        return (
            "referenced_record",
            status.HTTP_409_CONFLICT,
            "The record is referenced by other data and cannot be changed.",
        )
    if sqlstate == _SQLSTATE_CHECK:
        return (
            "invalid_state",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The request would violate a stored data invariant.",
        )
    return None


def _log(request, request_id, code, status_code, exc=None):
    fields = {
        "request_id": request_id,
        "code": code,
        "status": status_code,
        "method": getattr(request, "method", None),
        "path": getattr(request, "path", None),
        "duration_ms": duration_ms(request),
        "record_ids": record_ids(request),
    }
    if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        fields["exception"] = type(exc).__name__ if exc is not None else None
        fields["exception_message"] = str(exc) if exc is not None else None
        fields["traceback"] = (
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            if exc is not None
            else None
        )
        log_event(logging.ERROR, "request.failed", **fields)
    else:
        log_event(logging.WARNING, "request.rejected", **fields)


def _finalize(request, request_id, code, message, details, status_code, exc=None):
    _log(request, request_id, code, status_code, exc)
    return Response(
        _envelope(code, message, details, request_id), status=status_code
    )


def _wrap_drf_response(request, response, request_id):
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
        details = {}
    elif isinstance(data, dict):
        code, message, details = "invalid", "Request validation failed.", data
    else:
        code, message, details = "error", str(data), {}
    return _finalize(
        request, request_id, code, message, details, response.status_code
    )


def api_exception_handler(exc, context):
    """DRF exception handler implementing the contract above."""
    request = context.get("request")
    request_id = getattr(request, "request_id", None) or new_request_id()

    if isinstance(exc, ServiceError):
        code = exc.code
        return _finalize(
            request,
            request_id,
            code,
            exc.message,
            {},
            _status_for(code, _FALLBACK_SERVICE),
        )

    if isinstance(exc, DRFValidationError):
        details, message, code = _drf_validation(exc)
        return _finalize(
            request,
            request_id,
            code,
            message,
            details,
            _status_for(code, _FALLBACK_VALIDATION),
        )

    if isinstance(exc, DjangoValidationError):
        details, message, code = _django_validation(exc)
        return _finalize(
            request,
            request_id,
            code,
            message,
            details,
            _status_for(code, _FALLBACK_VALIDATION),
        )

    if isinstance(exc, IntegrityError):
        conflict = _database_conflict(exc)
        if conflict is not None:
            code, status_code, message = conflict
            return _finalize(request, request_id, code, message, {}, status_code)
        # Unmapped integrity failure: treat as an unexpected server fault.

    response = drf_exception_handler(exc, context)
    if response is not None:
        return _wrap_drf_response(request, response, request_id)

    return _finalize(
        request,
        request_id,
        "internal_error",
        "An unexpected error occurred.",
        {},
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        exc,
    )
