"""Request-ID and access-logging middleware.

* Accepts a well-formed client ``X-Request-ID`` or generates one, stores it on
  the request, and echoes it on every response.
* Logs successful (status < 400) requests here; error requests are logged with
  their semantic code and exception information by the API exception handler
  (``procurement.api.errors``), so every request is logged exactly once.
"""

import logging
import time

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
