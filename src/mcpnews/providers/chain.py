"""Chain execution with per-slot circuit breakers.

A chain is an ordered list of slots. Requests walk it, skipping open breakers,
and raise ``NoProviderAvailable`` when every slot is exhausted. Callers treat
that as "degrade to a lower tier", never as a crash — which is the whole reason
this subsystem exists.

    CLOSED --n failures--> OPEN --cooldown--> HALF-OPEN --success--> CLOSED
                                                       \\--failure--> OPEN
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from mcpnews.providers.errors import ProviderRequestError, ProviderUnavailable

log = logging.getLogger("mcpnews.providers")

T = TypeVar("T")


class NoProviderAvailable(Exception):
    """Every slot in the chain failed or is cooling down."""

    def __init__(self, chain: str, attempted: list[str] | None = None):
        super().__init__(f"no provider available for chain {chain!r}")
        self.chain = chain
        self.attempted = attempted or []


@dataclass
class FailoverPolicy:
    max_attempts_per_slot: int = 2
    backoff_initial_s: float = 1.0
    backoff_factor: float = 2.0
    open_after_failures: int = 3
    cooldown_s: float = 300.0
    probe_interval_s: float = 60.0
    #: Cost guard: never silently spend money because a local box rebooted.
    require_confirmation_for_paid_failover: bool = False

    @classmethod
    def from_dict(cls, raw: dict | None) -> FailoverPolicy:
        raw = raw or {}
        return cls(
            max_attempts_per_slot=int(raw.get("max_attempts_per_slot", 2)),
            backoff_initial_s=float(raw.get("backoff_initial_s", 1.0)),
            backoff_factor=float(raw.get("backoff_factor", 2.0)),
            open_after_failures=int(raw.get("open_after_failures", 3)),
            cooldown_s=float(raw.get("cooldown_s", 300.0)),
            probe_interval_s=float(raw.get("probe_interval_s", 60.0)),
            require_confirmation_for_paid_failover=bool(
                raw.get("require_confirmation_for_paid_failover", False)),
        )


@dataclass
class Breaker:
    """CLOSED -> OPEN after N consecutive failures -> HALF-OPEN after cooldown."""
    open_after: int = 3
    cooldown_s: float = 300.0
    failures: int = 0
    opened_at: float | None = None
    last_ok: float | None = None
    last_error: str | None = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if time.monotonic() - self.opened_at >= self.cooldown_s:
            return "half_open"
        return "open"

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self.last_error = None
        self.last_ok = time.time()

    def record_failure(self, error: str = "") -> None:
        self.failures += 1
        self.last_error = error[:300] or None
        if self.failures >= self.open_after and self.opened_at is None:
            self.opened_at = time.monotonic()

    def to_dict(self, slot: str) -> dict:
        return {
            "slot": slot, "state": self.state, "failures": self.failures,
            "last_ok": self.last_ok, "last_error": self.last_error,
        }


@dataclass
class Chain:
    """An ordered list of slots plus the breakers that guard them."""
    name: str
    slots: list[str] = field(default_factory=list)
    policy: FailoverPolicy = field(default_factory=FailoverPolicy)
    breakers: dict[str, Breaker] = field(default_factory=dict)
    #: slot name -> provider instance, or None when the slot is not configured.
    resolver: Callable[[str], Any] | None = None

    def __post_init__(self) -> None:
        for slot in self.slots:
            self.breakers.setdefault(slot, Breaker(
                open_after=self.policy.open_after_failures, cooldown_s=self.policy.cooldown_s))

    # ---- inspection ------------------------------------------------------
    def available_slots(self) -> list[str]:
        """Configured slots whose breaker is not open."""
        out = []
        for slot in self.slots:
            if self.resolver and self.resolver(slot) is None:
                continue
            if self.breakers[slot].state == "open":
                continue
            out.append(slot)
        return out

    def configured_slots(self) -> list[str]:
        if self.resolver is None:
            return list(self.slots)
        return [s for s in self.slots if self.resolver(s) is not None]

    def health(self) -> list[dict]:
        out = []
        for slot in self.slots:
            configured = self.resolver is None or self.resolver(slot) is not None
            d = self.breakers[slot].to_dict(slot)
            d["configured"] = configured
            if not configured:
                d["state"] = "unconfigured"
            out.append(d)
        return out

    # ---- the walk --------------------------------------------------------
    async def run(self, operation: Callable[[Any, str], Awaitable[T]]) -> tuple[T, str]:
        """Walk the chain. Returns (result, slot that served it).

        1. Skip any slot whose breaker is OPEN.
        2. Try the slot up to max_attempts_per_slot, with exponential backoff.
        3. On success, reset that slot's failure count and return.
        4. On exhaustion, record the failure, maybe open the breaker, move on.
        5. If every slot is exhausted, raise NoProviderAvailable.
        """
        attempted: list[str] = []
        for slot in self.slots:
            provider = self.resolver(slot) if self.resolver else None
            if provider is None:
                continue
            breaker = self.breakers[slot]
            if breaker.state == "open":
                continue
            attempted.append(slot)
            delay = self.policy.backoff_initial_s
            for attempt in range(1, self.policy.max_attempts_per_slot + 1):
                try:
                    result = await operation(provider, slot)
                except ProviderRequestError:
                    # Our bug. Failing over would repeat it and cost money twice.
                    raise
                except (TimeoutError, ProviderUnavailable, OSError) as exc:
                    log.info("chain %s slot %s attempt %d failed: %s",
                             self.name, slot, attempt, exc)
                    if attempt < self.policy.max_attempts_per_slot:
                        await asyncio.sleep(delay)
                        delay *= self.policy.backoff_factor
                        continue
                    breaker.record_failure(str(exc))
                else:
                    breaker.record_success()
                    return result, slot
        raise NoProviderAvailable(self.name, attempted)

    async def probe(self) -> None:
        """Background health check. Closes a half-open breaker that recovered."""
        for slot in self.slots:
            provider = self.resolver(slot) if self.resolver else None
            if provider is None:
                continue
            breaker = self.breakers[slot]
            if breaker.state != "half_open":
                continue
            try:
                ok = await provider.health()
            except Exception:
                ok = False
            if ok:
                breaker.record_success()
            else:
                breaker.opened_at = time.monotonic()
