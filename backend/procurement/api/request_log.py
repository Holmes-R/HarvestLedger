"""Structured request logging and request-ID helpers.

Logs are single-line JSON objects so they are machine-readable. They never
contain request/response bodies, credentials, banking references, review keys or
query strings -- only method, safe path, status, timing, request ID and the
non-sensitive numeric record IDs resolved from the URL.
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime

_logger = logging.getLogger("procurement.api")

REQUEST_ID_HEADER = "X-Request-ID"

#: A supplied request ID is accepted only if it is short, opaque and header-safe.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def new_request_id() -> str:
    return uuid.uuid4().hex


def is_valid_request_id(value) -> bool:
    return bool(value) and bool(_REQUEST_ID_RE.match(str(value)))


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def log_event(level: int, event: str, **fields) -> None:
    """Emit one structured JSON log line at ``level``."""
    payload = {
        "timestamp": utc_timestamp(),
        "level": logging.getLevelName(level),
        "event": event,
    }
    payload.update({key: value for key, value in fields.items()})
    _logger.log(level, json.dumps(payload, default=str))
