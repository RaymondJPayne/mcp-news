"""Feed date parsing.

Feeds carry RFC 822, RFC 3339, ISO 8601 and a long tail of things that are none
of those. Everything normalises to a UTC ISO-8601 string, because a comparison
between two different date formats in SQL is a silent bug.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

try:
    from dateutil import parser as _dateutil
except Exception:  # noqa: BLE001  - optional; the two stdlib paths cover most feeds
    _dateutil = None


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None

    # Numeric epoch, used by a few JSON APIs.
    if value.isdigit() and len(value) in (10, 13):
        seconds = int(value) / (1000 if len(value) == 13 else 1)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(timespec="seconds")

    for attempt in (_iso, _rfc822, _loose):
        got = attempt(value)
        if got is not None:
            return got
    return None


def _finish(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _iso(value: str) -> str | None:
    try:
        return _finish(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _rfc822(value: str) -> str | None:
    try:
        return _finish(parsedate_to_datetime(value))
    except (TypeError, ValueError):
        return None


def _loose(value: str) -> str | None:
    if _dateutil is None:
        return None
    try:
        return _finish(_dateutil.parse(value))
    except (ValueError, OverflowError, TypeError):
        return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
