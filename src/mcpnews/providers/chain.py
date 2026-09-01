"""Chain execution with per-slot circuit breakers.

A chain is an ordered list of slots. Requests walk it, skipping open breakers,
and raise NoProviderAvailable when every slot is exhausted. Callers treat that
as "degrade to a lower tier", never as a crash.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field


class NoProviderAvailable(Exception):
    """Every slot in the chain failed or is cooling down."""


@dataclass
class Breaker:
    """CLOSED -> OPEN after N consecutive failures -> HALF-OPEN after cooldown."""
    open_after: int = 3
    cooldown_s: float = 300.0
    failures: int = 0
    opened_at: float | None = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if time.time() - self.opened_at >= self.cooldown_s:
            return "half_open"
        return "open"

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.open_after and self.opened_at is None:
            self.opened_at = time.time()


@dataclass
class Chain:
    """TODO(phase-5): implement walk() over slots with backoff and breakers."""
    name: str
    slots: list[str] = field(default_factory=list)
    breakers: dict[str, Breaker] = field(default_factory=dict)
