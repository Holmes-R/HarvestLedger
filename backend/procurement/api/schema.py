"""Reusable OpenAPI building blocks for the M3 schema.

These objects are shared by the view annotations in :mod:`procurement.api.views`
so the cross-cutting parts of the contract -- the error envelope, the list
filters and ordering keys, the optional reviewer-clock headers and a set of
realistic examples -- are defined once and stay consistent with the actual
responses. Nothing here performs I/O or business logic.
"""

from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
)
from rest_framework import serializers

REQUEST_ID_HEADER = "X-Request-ID"
TEST_CLOCK_HEADER = "X-Test-Clock"
REVIEW_KEY_HEADER = "X-Review-Key"


# --- Error envelope ---------------------------------------------------------


class ErrorDetailSerializer(serializers.Serializer):
    """One field-level problem inside ``error.details``."""

    code = serializers.CharField(
        allow_null=True,
        help_text="Machine-readable code, or null when none applies.",
    )
    message = serializers.CharField(help_text="Human-readable explanation.")


class ErrorBodySerializer(serializers.Serializer):
    code = serializers.CharField(
        help_text="Stable machine-readable code, e.g. farmer_not_found."
    )
    message = serializers.CharField(help_text="Human-readable summary; safe to show.")
    details = serializers.DictField(
        child=serializers.ListField(child=ErrorDetailSerializer(), allow_empty=True),
        help_text=(
            "Field-keyed problems for validation errors; an empty object otherwise."
        ),
    )
    request_id = serializers.CharField(
        help_text="Request id, also returned in the X-Request-ID header."
    )


class ErrorEnvelopeSerializer(serializers.Serializer):
    """The single error shape returned by every endpoint."""

    error = ErrorBodySerializer()


class HealthSerializer(serializers.Serializer):
    """Liveness response."""

    status = serializers.CharField(help_text='Always "ok".')


def _error(status_code, description):
    return OpenApiResponse(response=ErrorEnvelopeSerializer, description=description)


#: The statuses every operation may return, with the meaning of each code family.
ERROR_RESPONSES = {
    400: _error(
        400,
        "Malformed request: bad field type, excess decimal precision, unknown "
        "ordering key, or an invalid/reversed date range.",
    ),
    403: _error(
        403,
        "Reviewer clock aid disabled or unauthorised (only when X-Test-Clock is "
        "sent).",
    ),
    404: _error(
        404,
        "Unknown resource, e.g. an absent farmer, crop, grade or original delivery.",
    ),
    409: _error(
        409,
        "Duplicate or forbidden state transition, e.g. a payout that is not a "
        "draft, or removing a grade that is still in use.",
    ),
    422: _error(
        422,
        "Domain rejection of a well-formed request, e.g. no applicable price or "
        "moisture above the crop maximum.",
    ),
    500: _error(
        500,
        "Unexpected server fault; the message is generic and nothing is leaked.",
    ),
}


def documented(success, extra=None):
    """Merge a success response map with the shared error responses."""
    result = dict(success)
    result.update(ERROR_RESPONSES)
    if extra:
        result.update(extra)
    return result


# --- Shared query parameters ------------------------------------------------


def ordering_parameter(fields, default):
    """An ``?ordering=`` parameter documenting the whitelist and tie-breaker."""
    allowed = ", ".join(f"`{field}`" for field in fields)
    return OpenApiParameter(
        name="ordering",
        type=str,
        description=(
            f"Sort key. One of {allowed}; prefix with '-' for descending. "
            f"Unknown keys are rejected with 400. Ordering always ends with a "
            f"fixed tie-breaker so paging is stable; default is {default}."
        ),
    )


FARMER_PARAM = OpenApiParameter(
    name="farmer", type=int, description="Filter by farmer id."
)
CROP_PARAM = OpenApiParameter(
    name="crop", type=int, description="Filter by crop id."
)
CROP_GRADE_PARAM = OpenApiParameter(
    name="crop_grade", type=int, description="Filter by crop-grade id."
)
SEARCH_PARAM = OpenApiParameter(
    name="search",
    type=str,
    description="Case-insensitive substring match on name, phone or village.",
)
FROM_PARAM = OpenApiParameter(
    name="from",
    type=str,
    description="ISO-8601 date; inclusive lower bound on the business date.",
)
TO_PARAM = OpenApiParameter(
    name="to",
    type=str,
    description="ISO-8601 date; inclusive upper bound on the business date.",
)
STATUS_PARAM = OpenApiParameter(
    name="status",
    type=str,
    description="Payout status: DRAFT, FINALISED or PAID.",
)
WEEK_PARAM = OpenApiParameter(
    name="week",
    type=str,
    description=(
        "Any ISO-8601 date; matched to the Monday-based week containing it "
        "(compared against week_start)."
    ),
)
PAYOUT_PARAM = OpenApiParameter(
    name="payout", type=int, description="Filter by payout id."
)
ORIGINAL_PARAM = OpenApiParameter(
    name="original_delivery",
    type=int,
    description="Filter corrections by the delivery they adjust.",
)
DELIVERY_KIND_PARAM = OpenApiParameter(
    name="kind",
    type=str,
    description="Delivery kind: PROCUREMENT, CREDIT_NOTE or DEBIT_NOTE.",
)
CORRECTION_KIND_PARAM = OpenApiParameter(
    name="kind",
    type=str,
    description="Correction kind: CREDIT_NOTE or DEBIT_NOTE.",
)
EVENT_TYPE_PARAM = OpenApiParameter(
    name="event_type",
    type=str,
    description="Ledger event type: DELIVERY, CORRECTION, ADVANCE or PAYOUT.",
)

#: The optional, demo-only reviewer-clock headers (see README section 10.1).
REVIEW_CLOCK_HEADERS = [
    OpenApiParameter(
        name=TEST_CLOCK_HEADER,
        type=str,
        location=OpenApiParameter.HEADER,
        description=(
            "Optional reviewer aid (demo-only): a timezone-aware ISO-8601 instant "
            "that pins the business clock for this one request. Ignored unless the "
            "aid is enabled server-side and a matching X-Review-Key is supplied; it "
            "changes business dates only (audit timestamps and logs stay on real "
            "time). Disabled -> 403 review_clock_disabled; missing/wrong key -> 403 "
            "review_clock_unauthorized; malformed or naive -> 400 review_clock_invalid."
        ),
    ),
    OpenApiParameter(
        name=REVIEW_KEY_HEADER,
        type=str,
        location=OpenApiParameter.HEADER,
        description=(
            "Shared secret authorising X-Test-Clock. Never logged or echoed."
        ),
    ),
]


# --- Examples ---------------------------------------------------------------

ERROR_EXAMPLE = OpenApiExample(
    "Validation error",
    value={
        "error": {
            "code": "price_not_found",
            "message": (
                "No effective price for crop grade A on or before 2026-01-05."
            ),
            "details": {},
            "request_id": "3f2c1b0a9d8e7f60",
        }
    },
    response_only=True,
    status_codes=["422"],
)

DELIVERY_PREVIEW_EXAMPLE = OpenApiExample(
    "Maize grade A, 100 kg at 14% moisture",
    value={
        "farmer_id": 1,
        "crop_grade": 5,
        "delivered_on": "2026-01-05",
        "accounting_date": "2026-01-05",
        "business_date": "2026-01-05",
        "gross_weight_kg": "100.000",
        "moisture_percent": "14.00",
        "threshold_used": "14.00",
        "applied_price": "24.50",
        "price_list_entry": 12,
        "deduction_percent": "0.00",
        "deduction_kg": "0.00000",
        "net_kg": "100.00000",
        "amount": "2450.00",
    },
    response_only=True,
    status_codes=["200"],
)

CORRECTION_EXAMPLE = OpenApiExample(
    "Credit note of 245.00",
    value={
        "id": 41,
        "farmer": 1,
        "kind": "CREDIT_NOTE",
        "original_delivery": 7,
        "correction_magnitude": "245.00",
        "reason": "Returned to farmer",
        "accounting_date": "2026-01-12",
        "amount": "245.00",
        "payout": None,
        "recorded_at": "2026-01-12T04:15:00.000000Z",
    },
    response_only=True,
    status_codes=["201"],
)

LEDGER_PAGE_EXAMPLE = OpenApiExample(
    "First page of a farmer's ledger",
    value={
        "count": 2,
        "next": None,
        "previous": None,
        "summary": {
            "farmer_id": 1,
            "name": "Asha",
            "phone": "9000000001",
            "outstanding_advance": "1000.00",
            "reconciliation": {
                "farmer_id": 1,
                "total_advances": "1000.00",
                "total_recovered": "0.00",
                "expected_outstanding": "1000.00",
                "stored_outstanding": "1000.00",
                "difference": "0.00",
                "is_reconciled": True,
            },
            "total_advances": "1000.00",
            "settled_earnings": "0.00",
            "total_recovered": "0.00",
            "draft_projection": "0.00",
            "unassigned_earnings": "2450.00",
            "total_recorded_amount": "3450.00",
            "earnings_identity_holds": True,
            "is_reconciled": True,
            "history_from": "2026-01-05",
            "history_to": "2026-01-05",
        },
        "results": [
            {
                "event_type": "ADVANCE",
                "id": 3,
                "date": "2026-01-05",
                "amount": "1000.00",
                "delivery": None,
                "advance": {
                    "id": 3,
                    "amount": "1000.00",
                    "given_on": "2026-01-05",
                    "created_at": "2026-01-05T03:00:00.000000Z",
                },
                "payout": None,
            },
            {
                "event_type": "DELIVERY",
                "id": 7,
                "date": "2026-01-05",
                "amount": "2450.00",
                "delivery": {
                    "id": 7,
                    "kind": "PROCUREMENT",
                    "crop_grade": 5,
                    "delivered_on": "2026-01-05",
                    "accounting_date": "2026-01-05",
                    "gross_weight_kg": "100.000",
                    "moisture_percent": "14.00",
                    "net_kg": "100.00000",
                    "applied_price": "24.50",
                    "amount": "2450.00",
                    "payout": None,
                    "original_delivery": None,
                    "correction_magnitude": None,
                    "reason": "",
                    "is_correction": False,
                    "is_assigned": False,
                    "signed_amount": "2450.00",
                },
                "advance": None,
                "payout": None,
            },
        ],
    },
    response_only=True,
    status_codes=["200"],
)

_DELIVERY_MEMBER = {
    "id": 7,
    "farmer": 1,
    "kind": "PROCUREMENT",
    "crop_grade": 5,
    "delivered_on": "2026-01-05",
    "accounting_date": "2026-01-05",
    "gross_weight_kg": "100.000",
    "moisture_percent": "14.00",
    "threshold_used": "14.00",
    "deduction_percent": "0.00",
    "deduction_kg": "0.00000",
    "net_kg": "100.00000",
    "applied_price": "24.50",
    "price_list_entry": 12,
    "amount": "2450.00",
    "calculation_version": 1,
    "original_delivery": None,
    "correction_magnitude": None,
    "reason": "",
    "payout": 9,
    "recorded_at": "2026-01-05T03:10:00.000000Z",
}

PAYOUT_GENERATE_CREATED_EXAMPLE = OpenApiExample(
    "Draft payout created",
    value={
        "payout": {
            "id": 9,
            "farmer": 1,
            "farmer_name": "Asha",
            "week_start": "2026-01-05",
            "week_end": "2026-01-11",
            "status": "DRAFT",
            "gross_amount": "2450.00",
            "advance_deduction": "0.00",
            "net_amount": "2450.00",
            "deliveries": [_DELIVERY_MEMBER],
            "created_at": "2026-01-05T03:20:00.000000Z",
            "finalised_at": None,
            "paid_at": None,
        },
        "reason": None,
    },
    response_only=True,
    status_codes=["201"],
)

PAYOUT_GENERATE_EMPTY_EXAMPLE = OpenApiExample(
    "Empty week (successful no-op)",
    value={"payout": None, "reason": "NO_ELIGIBLE_DELIVERIES"},
    response_only=True,
    status_codes=["200"],
)

PAYOUT_FINALISED_EXAMPLE = OpenApiExample(
    "Finalised statement",
    value={
        "id": 9,
        "farmer": 1,
        "farmer_name": "Asha",
        "week_start": "2026-01-05",
        "week_end": "2026-01-11",
        "status": "FINALISED",
        "gross_amount": "2450.00",
        "advance_deduction": "1000.00",
        "net_amount": "1450.00",
        "deliveries": [_DELIVERY_MEMBER],
        "created_at": "2026-01-05T03:20:00.000000Z",
        "finalised_at": "2026-01-12T03:00:00.000000Z",
        "paid_at": None,
    },
    response_only=True,
    status_codes=["200"],
)
