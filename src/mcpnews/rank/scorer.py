"""Profile scoring. No model, no network, no randomness.

INVARIANT: the score returned here is INTEREST ONLY. Recency is never applied.
Merging the two makes a month-old article score near zero however well it
matches, which silently destroys historical search and any backfill. Decay is a
query-time view parameter — see search/views.py. Pinned by
tests/test_scoring_invariants.py.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RuleHit:
    name: str
    section: str
    points: float
    hits: int
    in_title: bool


@dataclass
class Score:
    total: float
    rules: list[RuleHit]

    def explain(self) -> str:
        if not self.rules:
            return "no rules matched"
        return "; ".join(f"{r.name} +{r.points:.1f}" for r in self.rules)


def score(title: str, body: str, domain: str, meta: dict, profile) -> Score:
    """TODO(phase-2): word-boundary matching, weights, caps, must_include, mute."""
    raise NotImplementedError
