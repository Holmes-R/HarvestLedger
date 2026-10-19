"""Request-ID, access-logging and reviewer-clock middleware.

* :class:`RequestIDMiddleware` accepts a well-formed client ``X-Request-ID`` or
  generates one, stores it on the request, and echoes it on every response. It
  logs successful (status < 400) requests; error requests are logged with their
  semantic code and exception information by the API exception handler
  (``procurement.api.errors``), so every request is logged exactly once.
* :class:`ReviewClockMiddleware` is the gated reviewer aid described in README
  section 10. When enabled (``ALLOW_REVIEW_CLOCK``) and authorised (a matching
  ``REVIEW_CLOCK_KEY`` in ``X-Review-Key``), a request may pin the *business*
  clock with an ISO-8601 ``X-Test-Clock`` instant. The override is request-local
  (``contextvars``), so it never mutates global time or shared service state and
  audit timestamps / request logs stay on real time.
"""

import logging
import secrets
import time

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status

from procurement.clock import FrozenClock, use_clock

from .request_log import (
    REQUEST_ID_HEADER,
    is_valid_request_id,
    log_event,
    new_request_id,
)


def record_ids(request):
    """Non-sensitive record IDs resolved from the URL (never the query string)."""
    match = getattr(request, "resolver_match", None)
    kwargs = getattr(match, "kwargs", None) or {}
    return {
        key: value
        for key, value in kwargs.items()
        if isinstance(value, int) or (isinstance(value, str) and len(value) <= 64)
    }


def duration_ms(request):
    started = getattr(request, "_api_start_time", None)
    if started is None:
        return None
    return round((time.monotonic() - started) * 1000, 2)


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied = request.headers.get(REQUEST_ID_HEADER)
        request.request_id = (
            supplied if is_valid_request_id(supplied) else new_request_id()
        )
        request._api_start_time = time.monotonic()

        response = self.get_response(request)

        response[REQUEST_ID_HEADER] = request.request_id
        if response.status_code < 400:
            log_event(
                logging.INFO,
                "request.completed",
                request_id=request.request_id,
                method=request.method,
                path=request.path,
                status=response.status_code,
                duration_ms=duration_ms(request),
                record_ids=record_ids(request),
            )
        return response


#: Header carrying the reviewer-supplied business instant (ISO-8601, tz-aware).
TEST_CLOCK_HEADER = "X-Test-Clock"
#: Header carrying the shared secret that authorises the override.
REVIEW_KEY_HEADER = "X-Review-Key"

DISABLED_MESSAGE = "The reviewer clock aid is disabled."
UNAUTHORIZED_MESSAGE = "A valid review key is required to change the business clock."
INVALID_MESSAGE = "The X-Test-Clock header must be a timezone-aware ISO-8601 timestamp."


def _reject(request, code, message, status_code):
    """Log a rejection and return the shared error envelope.

    Mirrors ``procurement.api.errors`` without importing it (which would be a
    cycle). ``RequestIDMiddleware`` wraps this middleware, so ``request_id`` is
    already set and the ``X-Request-ID`` header is added to this response there.
    The review key and any header value are deliberately never logged.
    """
    request_id = getattr(request, "request_id", None)
    log_event(
        logging.WARNING,
        "request.rejected",
        request_id=request_id,
        code=code,
        status=status_code,
        method=request.method,
        path=request.path,
        duration_ms=duration_ms(request),
        record_ids=record_ids(request),
    )
    return JsonResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "details": {},
                "request_id": request_id,
            }
        },
        status=status_code,
    )


class ReviewClockMiddleware:
    """Request-local, gated business-clock override for reviewers.

    An override is attempted only when ``X-Test-Clock`` is present. The request
    is rejected unless the aid is enabled and a matching ``X-Review-Key`` is
    supplied; the timestamp must be a timezone-aware ISO-8601 instant. On
    success the clock is installed for the lifetime of the request via a
    ``contextvars`` override and always restored afterwards.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied_clock = request.headers.get(TEST_CLOCK_HEADER)
        if supplied_clock is None:
            return self.get_response(request)

        if not getattr(settings, "ALLOW_REVIEW_CLOCK", False):
            return _reject(
                request,
                "review_clock_disabled",
                DISABLED_MESSAGE,
                status.HTTP_403_FORBIDDEN,
            )

        expected_key = getattr(settings, "REVIEW_CLOCK_KEY", "") or ""
        presented_key = request.headers.get(REVIEW_KEY_HEADER) or ""
        authorised = expected_key and secrets.compare_digest(
            presented_key.encode(), expected_key.encode()
        )
        if not authorised:
            return _reject(
                request,
                "review_clock_unauthorized",
                UNAUTHORIZED_MESSAGE,
                status.HTTP_403_FORBIDDEN,
            )

        try:
            instant = parse_datetime(supplied_clock.strip())
        except (AttributeError, TypeError, ValueError):
            instant = None
        if instant is None or timezone.is_naive(instant):
            return _reject(
                request,
                "review_clock_invalid",
                INVALID_MESSAGE,
                status.HTTP_400_BAD_REQUEST,
            )

        with use_clock(FrozenClock(instant)):
            return self.get_response(request)
