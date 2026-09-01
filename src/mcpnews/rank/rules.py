"""Rule types: how a profile rule decides whether it fired.

One type ships — whole-word keyword matching — and it is the only one the
documented profile schema needs. The registry exists so a contributor can add,
say, a regular-expression or a proximity rule without touching the scorer.

Word boundaries are the whole point. A rule for "Ace" must not fire on "space",
"surface" or "peace"; a rule for "AI Act" must not fire on "AI Actuator".
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable

_REGISTRY: dict[str, type[RuleType]] = {}


def register(name: str) -> Callable[[type], type]:
    def deco(cls: type) -> type:
        _REGISTRY[name] = cls  # type: ignore[assignment]
        return cls
    return deco


def get_rule_type(name: str) -> type[RuleType]:
    if name not in _REGISTRY:
        raise KeyError(f"unknown rule type {name!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def registered() -> list[str]:
    return sorted(_REGISTRY)


_WORDISH = re.compile(r"\w")


def _alternative(term: str) -> str:
    """One term as a regex alternative, with boundaries only where they make sense.

    Internal whitespace becomes flexible, so "export  control" and "export\\ncontrol"
    both match a rule written "export control".
    """
    term = term.strip()
    if not term:
        return ""
    parts = [re.escape(p) for p in term.split()]
    core = r"\s+".join(parts)
    lead = r"(?<!\w)" if _WORDISH.match(term[0]) else ""
    tail = r"(?!\w)" if _WORDISH.match(term[-1]) else ""
    return f"{lead}(?:{core}){tail}"


def compile_terms(terms: list[str]) -> re.Pattern[str] | None:
    """Compile a set of terms into one case-insensitive, word-boundary pattern.

    Longest first, so "AI Act" is preferred over "AI" and a single match is not
    double counted.
    """
    alts = [a for a in (_alternative(t) for t in sorted(set(terms), key=len, reverse=True)) if a]
    if not alts:
        return None
    return re.compile("|".join(alts), re.IGNORECASE | re.UNICODE)


class RuleType(ABC):
    """How many times does this rule fire in this text?"""

    @abstractmethod
    def count(self, text: str) -> int: ...

    @abstractmethod
    def present(self, text: str) -> bool: ...


@register("keyword")
class KeywordRule(RuleType):
    """Whole-word, case-insensitive, deterministic. No model, no network."""

    __slots__ = ("_pattern",)

    def __init__(self, terms: list[str]):
        self._pattern = compile_terms(terms)

    def count(self, text: str) -> int:
        if self._pattern is None or not text:
            return 0
        return sum(1 for _ in self._pattern.finditer(text))

    def present(self, text: str) -> bool:
        if self._pattern is None or not text:
            return False
        return self._pattern.search(text) is not None
