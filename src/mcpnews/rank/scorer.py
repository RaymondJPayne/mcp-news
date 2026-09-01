"""Profile scoring. No model, no network, no randomness.

INVARIANT: the score returned here is INTEREST ONLY. Recency is never applied.
Merging the two makes a month-old article score near zero however well it
matches, which silently destroys historical search and any backfill. Decay is a
query-time view parameter — see ``search/views.py``. Pinned by
``tests/test_scoring_invariants.py``.

The procedure is exactly the one in docs/PROFILE.md:

1. Match each rule against title, body and metadata on word boundaries.
2. Title matches multiply by ``in_title_multiplier``.
3. Sum the hits per rule, then cap at ``cap_per_rule``.
4. Apply source boost or penalty.
5. Drop to zero if any mute rule matches.
6. Return the total with the list of rules that fired.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcpnews.config.profile import Profile, Rule
from mcpnews.rank.rules import KeywordRule, compile_terms


@dataclass
class RuleHit:
    name: str
    section: str
    points: float
    hits: int
    in_title: bool
    weight: float = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "section": self.section,
            "points": round(self.points, 3),
            "hits": self.hits,
            "in_title": self.in_title,
            "weight": self.weight,
        }


@dataclass
class Score:
    total: float
    rules: list[RuleHit] = field(default_factory=list)
    muted: bool = False
    muted_by: str = ""

    def explain(self) -> str:
        if self.muted:
            return f"muted by {self.muted_by}"
        if not self.rules:
            return "no rules matched"
        return "; ".join(f"{r.name} +{r.points:.1f}" for r in self.rules)

    def to_dict(self) -> dict:
        return {
            "total": round(self.total, 3),
            "rules": [r.to_dict() for r in self.rules],
            "muted": self.muted,
            "muted_by": self.muted_by,
        }


def _domain_matches(domain: str, pattern: str) -> bool:
    """``example.com`` in the profile matches ``news.example.com`` too."""
    domain = (domain or "").lower().lstrip(".")
    pattern = (pattern or "").lower().lstrip(".")
    if not domain or not pattern:
        return False
    return domain == pattern or domain.endswith("." + pattern)


def _meta_text(meta: dict[str, Any] | None) -> str:
    if not meta:
        return ""
    bits: list[str] = []
    for key in ("summary", "source_name", "region", "author", "section"):
        v = meta.get(key)
        if isinstance(v, str) and v:
            bits.append(v)
    topics = meta.get("topics")
    if isinstance(topics, (list, tuple)):
        bits.extend(str(t) for t in topics)
    elif isinstance(topics, str):
        bits.append(topics)
    return "\n".join(bits)


class _CompiledRule:
    __slots__ = ("rule", "matcher", "must", "excl")

    def __init__(self, rule: Rule):
        self.rule = rule
        self.matcher = KeywordRule(rule.terms)
        self.must = KeywordRule(rule.must_include) if rule.must_include else None
        self.excl = KeywordRule(rule.exclude) if rule.exclude else None


class CompiledProfile:
    """A profile with every pattern compiled once.

    Scoring a corpus of a hundred thousand articles recompiles nothing.
    """

    def __init__(self, profile: Profile):
        self.profile = profile
        self.rules = [_CompiledRule(r) for r in profile.rules()]
        self.mute_keywords = compile_terms(profile.mute_keywords)

    def score(self, title: str, body: str, domain: str,
              meta: dict[str, Any] | None = None) -> Score:
        title = title or ""
        body = body or ""
        extra = _meta_text(meta)
        non_title = f"{body}\n{extra}" if extra else body
        haystack = f"{title}\n{non_title}"
        cap = self.profile.scoring.cap_per_rule

        # 5, taken first: a muted article is zero regardless of everything else.
        for pattern in self.profile.mute_domains:
            if _domain_matches(domain, pattern):
                return Score(0.0, [], muted=True, muted_by=pattern)
        if self.mute_keywords is not None:
            m = self.mute_keywords.search(haystack)
            if m:
                return Score(0.0, [], muted=True, muted_by=m.group(0))

        hits: list[RuleHit] = []
        total = 0.0
        for c in self.rules:
            r = c.rule
            # must_include / exclude gate the whole rule before anything is counted.
            if c.must is not None and not all(
                    KeywordRule([term]).present(haystack) for term in r.must_include):
                continue
            if c.excl is not None and c.excl.present(haystack):
                continue

            title_hits = c.matcher.count(title)
            body_hits = c.matcher.count(non_title)
            if not (title_hits or body_hits):
                continue

            weighted = title_hits * r.in_title_multiplier + body_hits
            points = min(r.weight * weighted, cap)
            if points <= 0:
                continue
            total += points
            hits.append(RuleHit(
                name=r.name, section=r.section, points=points,
                hits=title_hits + body_hits, in_title=title_hits > 0, weight=r.weight,
            ))

        # 4. Source preference is a multiplier on the whole article, not a rule.
        multiplier = 1.0
        applied: list[str] = []
        for table in (self.profile.source_boost, self.profile.source_penalty):
            for pattern, value in table.items():
                if _domain_matches(domain, pattern):
                    multiplier *= float(value)
                    applied.append(pattern)
        if applied and total > 0 and multiplier != 1.0:
            before = total
            total *= multiplier
            hits.append(RuleHit(
                name=applied[0], section="source", points=total - before,
                hits=1, in_title=False, weight=multiplier,
            ))

        hits.sort(key=lambda h: h.points, reverse=True)
        return Score(round(total, 4), hits)


def score(title: str, body: str, domain: str, meta: dict | None, profile: Profile) -> Score:
    """Convenience wrapper. Compile once with CompiledProfile when scoring many."""
    return CompiledProfile(profile).score(title, body, domain, meta)
