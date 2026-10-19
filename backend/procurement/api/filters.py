"""Query-parameter parsing shared by the M3 list endpoints.

Two rules are enforced here so they cannot drift between views:

* **Date filters are inclusive on both ends** (``>=`` for ``from`` / ``<=`` for
  ``to``), and an inverted range (``from`` after ``to``) is a ``400``.
* **Ordering is whitelisted per view.** A client may only name a field the view
  declares; anything else is a ``400`` (never an arbitrary ORM expression), and
  the chosen ordering is always completed with a unique id tie-breaker so the
  page sequence is deterministic.
"""

from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError as DRFValidationError


def _invalid(name, message):
    return DRFValidationError({name: [{"code": "invalid", "message": message}]})


def parse_int(value, name):
    """Parse a query-parameter integer or raise a ``400`` for ``name``."""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(name, "A valid integer is required.") from exc


def parse_date_param(value, name):
    """Parse an ISO-8601 date or raise a ``400`` for ``name``.

    Also rejects well-formatted but impossible dates (``2026-13-01``), which
    Django's ``parse_date`` signals with ``ValueError`` rather than ``None``.
    """
    try:
        parsed = parse_date(value)
    except ValueError:
        parsed = None
    if parsed is None:
        raise _invalid(name, "A valid date (YYYY-MM-DD) is required.")
    return parsed


def date_range(params, *, start="from", end="to"):
    """Return the inclusive ``(since, until)`` bounds declared by ``params``.

    Both ends are inclusive. A present-but-unparseable bound or a ``from`` later
    than ``to`` is a ``400``; absent bounds are ``None``.
    """
    since = parse_date_param(params[start], start) if start in params else None
    until = parse_date_param(params[end], end) if end in params else None
    if since is not None and until is not None and since > until:
        raise _invalid(start, "'from' must not be after 'to'.")
    return since, until


def _selected_ordering(raw, allowed):
    direction = "-" if raw.startswith("-") else ""
    field = raw[len(direction):]
    if field not in allowed:
        options = ", ".join(sorted(allowed))
        raise _invalid(
            "ordering", f"Ordering must be one of: {options}."
        )
    return direction, field


def order_queryset(raw, queryset, allowed, default):
    """Apply a whitelisted ordering, completing it with an id tie-breaker."""
    if not raw:
        return queryset.order_by(*default)
    direction, field = _selected_ordering(raw, allowed)
    keys = [f"{direction}{field}"]
    if field not in ("id", "pk"):
        keys.append(f"{direction}id")
    return queryset.order_by(*keys)


def order_events(raw, events, allowed, default, tiebreakers=("event_type", "id")):
    """Order an in-memory event timeline deterministically.

    Uses stable multi-pass sorting so a chosen primary field may sort in either
    direction while the fixed ``tiebreakers`` (by default ``event_type`` then
    ``id``) always disambiguate equal keys.
    """
    if not raw:
        keys = list(default)
    else:
        direction, field = _selected_ordering(raw, allowed)
        keys = [f"{direction}{field}"]
    for name in tiebreakers:
        if not any(key.lstrip("-") == name for key in keys):
            keys.append(name)

    ordered = list(events)
    for key in reversed(keys):
        reverse = key.startswith("-")
        name = key[1:] if reverse else key
        ordered.sort(key=lambda event: event[name], reverse=reverse)
    return ordered
