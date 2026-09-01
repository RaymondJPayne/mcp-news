"""Query-time views over stored scores.

Freshness lives here and nowhere else. The stored ``interest_score`` answers
"does this match what I care about"; a *view* answers "and how much do I care
right now". Keeping them apart is what makes historical search and offline
re-ranking possible at all — see docs/ARCHITECTURE.md.
"""
from __future__ import annotations

from datetime import UTC, datetime

#: A half-life of zero (or None) means no decay: the historical lens.
NO_DECAY = 0.0


def age_hours(published_at: str | datetime | None, *, now: datetime | None = None) -> float:
    if published_at is None:
        return 0.0
    now = now or datetime.now(UTC)
    if isinstance(published_at, str):
        try:
            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
    else:
        dt = published_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def decay_factor(hours: float, half_life_h: float | None) -> float:
    """0.5 ** (age / half_life). 1.0 when decay is switched off."""
    if not half_life_h or half_life_h <= 0:
        return 1.0
    return 0.5 ** (max(0.0, hours) / float(half_life_h))


def display_score(interest_score: float, published_at, half_life_h: float | None,
                  *, now: datetime | None = None) -> float:
    """What the feed sorts on. Never written back to the store."""
    return float(interest_score) * decay_factor(age_hours(published_at, now=now), half_life_h)
