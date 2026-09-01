"""One definition of what counts as a failure, shared by every adapter.

The distinction has teeth. Connection errors, timeouts, 5xx and 429 are the
provider's problem: fail over, trip the breaker. A 400 is *our* problem — a
malformed request — and failing over would repeat the same bad request against a
second provider and double the cost for the same answer.
"""
from __future__ import annotations

from mcpnews.providers.base import ProviderRequestError, ProviderUnavailable

__all__ = ["ProviderUnavailable", "ProviderRequestError", "classify_status", "raise_for_status"]

#: 408 and 425 are timing, 409 is contention, 429 is rate limiting. All retryable.
_RETRYABLE_4XX = {408, 409, 425, 429}


def classify_status(status: int) -> type[Exception] | None:
    """The exception class a status code deserves, or None when it is fine."""
    if status < 400:
        return None
    if status >= 500 or status in _RETRYABLE_4XX:
        return ProviderUnavailable
    return ProviderRequestError


def raise_for_status(status: int, body: str = "", *, slot: str = "") -> None:
    kind = classify_status(status)
    if kind is None:
        return
    where = f"{slot}: " if slot else ""
    raise kind(f"{where}HTTP {status}: {body[:300]}")
