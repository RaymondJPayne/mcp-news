"""The profile: the whole ranking model, as a file the reader can read.

Edited through the dashboard, stored as YAML exactly as documented in
``docs/PROFILE.md``, so it stays inspectable, diffable and portable. There is no
second, hidden model anywhere in this project.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcpnews import paths
from mcpnews.config.yamlio import read_yaml, write_yaml

PROFILE_FILENAME = "profile.yaml"

#: Sections that hold a list of rules. Order fixes the display order in the UI.
RULE_SECTIONS = ("identity", "interests", "places", "organisations")

_HEADER = """\
# THIS FILE IS THE ALGORITHM.
#
# Every article is scored by matching these rules; the dashboard shows which
# ones fired on every item. There is no second, hidden model. Edited from the
# Interests screen, but yours to read, copy and version-control.
#
# See docs/PROFILE.md.
"""


class ProfileError(ValueError):
    """A profile that cannot be used. Carries a message key for the UI."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass
class Rule:
    name: str
    section: str = "interests"
    match: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    weight: float = 3.0
    in_title_multiplier: float = 2.0

    @property
    def terms(self) -> list[str]:
        """What actually gets matched. A rule with no explicit terms matches its name."""
        return [t for t in (self.match or [self.name]) if t.strip()]


@dataclass
class Scoring:
    min_score: float = 1.0
    cap_per_rule: float = 16.0
    default_half_life_h: float = 36.0
    default_in_title_multiplier: float = 2.0


@dataclass
class Profile:
    version: int = 1
    identity: list[Rule] = field(default_factory=list)
    interests: list[Rule] = field(default_factory=list)
    places: list[Rule] = field(default_factory=list)
    organisations: list[Rule] = field(default_factory=list)
    source_boost: dict[str, float] = field(default_factory=dict)
    source_penalty: dict[str, float] = field(default_factory=dict)
    mute_domains: list[str] = field(default_factory=list)
    mute_keywords: list[str] = field(default_factory=list)
    scoring: Scoring = field(default_factory=Scoring)

    def rules(self) -> list[Rule]:
        out: list[Rule] = []
        for section in RULE_SECTIONS:
            out.extend(getattr(self, section))
        return out

    def to_dict(self) -> dict[str, Any]:
        def dump(rules: list[Rule]) -> list[dict]:
            items = []
            for r in rules:
                d: dict[str, Any] = {"name": r.name}
                if r.match:
                    d["match"] = list(r.match)
                if r.must_include:
                    d["must_include"] = list(r.must_include)
                if r.exclude:
                    d["exclude"] = list(r.exclude)
                d["weight"] = _clean_number(r.weight)
                if r.in_title_multiplier != self.scoring.default_in_title_multiplier:
                    d["in_title_multiplier"] = _clean_number(r.in_title_multiplier)
                items.append(d)
            return items

        ident = dump(self.identity)
        return {
            "version": self.version,
            # identity is a single person in the documented schema, but a list is
            # the same shape with one fewer special case in every consumer.
            "identity": ident[0] if len(ident) == 1 else ident,
            "interests": dump(self.interests),
            "places": dump(self.places),
            "organisations": dump(self.organisations),
            "sources": {"boost": dict(self.source_boost), "penalty": dict(self.source_penalty)},
            "mute": {"domains": list(self.mute_domains), "keywords": list(self.mute_keywords)},
            "scoring": {
                "min_score": _clean_number(self.scoring.min_score),
                "cap_per_rule": _clean_number(self.scoring.cap_per_rule),
                "default_half_life_h": _clean_number(self.scoring.default_half_life_h),
                "default_in_title_multiplier":
                    _clean_number(self.scoring.default_in_title_multiplier),
            },
        }


def _clean_number(v: float) -> float | int:
    return int(v) if float(v).is_integer() else round(float(v), 4)


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [p.strip() for p in v.split(",") if p.strip()]
    if isinstance(v, (list, tuple)):
        return [str(p).strip() for p in v if str(p).strip()]
    raise ProfileError(f"expected a list, got {type(v).__name__}")


def _rule_from(raw: Any, section: str, default_multiplier: float) -> Rule:
    if not isinstance(raw, dict):
        raise ProfileError(f"{section}: each entry must be a mapping")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ProfileError(f"{section}: every entry needs a name")
    try:
        weight = float(raw.get("weight", 3))
    except (TypeError, ValueError):
        raise ProfileError(f"{name}: weight must be a number") from None
    if not 0 < weight <= 100:
        raise ProfileError(f"{name}: weight must be between 0 and 100")
    try:
        mult = float(raw.get("in_title_multiplier", default_multiplier))
    except (TypeError, ValueError):
        raise ProfileError(f"{name}: in_title_multiplier must be a number") from None
    if mult < 0:
        raise ProfileError(f"{name}: in_title_multiplier cannot be negative")
    match = _as_list(raw.get("match"))
    # Aliases are just more ways to say the same thing.
    match += [a for a in _as_list(raw.get("aliases")) if a not in match]
    return Rule(
        name=name,
        section=section,
        match=match,
        must_include=_as_list(raw.get("must_include")),
        exclude=_as_list(raw.get("exclude")),
        weight=weight,
        in_title_multiplier=mult,
    )


def from_dict(raw: dict) -> Profile:
    if not isinstance(raw, dict):
        raise ProfileError("the profile must be a mapping")
    sc_raw = raw.get("scoring") or {}
    try:
        scoring = Scoring(
            min_score=float(sc_raw.get("min_score", 1.0)),
            cap_per_rule=float(sc_raw.get("cap_per_rule", 16.0)),
            default_half_life_h=float(sc_raw.get("default_half_life_h", 36.0)),
            default_in_title_multiplier=float(sc_raw.get("default_in_title_multiplier", 2.0)),
        )
    except (TypeError, ValueError):
        raise ProfileError("scoring values must be numbers") from None
    if scoring.cap_per_rule <= 0:
        raise ProfileError("cap_per_rule must be greater than zero")
    if scoring.default_half_life_h < 0:
        raise ProfileError("default_half_life_h cannot be negative")

    p = Profile(version=int(raw.get("version", 1)), scoring=scoring)
    for section in RULE_SECTIONS:
        entries = raw.get(section)
        if entries is None:
            continue
        if isinstance(entries, dict):       # identity is documented as a single mapping
            entries = [entries]
        if not isinstance(entries, list):
            raise ProfileError(f"{section} must be a list")
        setattr(p, section,
                [_rule_from(e, section, scoring.default_in_title_multiplier) for e in entries])

    src = raw.get("sources") or {}
    for key, target in (("boost", "source_boost"), ("penalty", "source_penalty")):
        vals = src.get(key) or {}
        if not isinstance(vals, dict):
            raise ProfileError(f"sources.{key} must be a mapping of domain to multiplier")
        cleaned = {}
        for domain, mult in vals.items():
            try:
                cleaned[str(domain).strip().lower()] = float(mult)
            except (TypeError, ValueError):
                raise ProfileError(f"sources.{key}.{domain} must be a number") from None
        setattr(p, target, cleaned)

    mute = raw.get("mute") or {}
    p.mute_domains = [d.lower() for d in _as_list(mute.get("domains"))]
    p.mute_keywords = _as_list(mute.get("keywords"))
    return p


def profile_path() -> Path:
    return paths.config_dir() / PROFILE_FILENAME


def exists() -> bool:
    return profile_path().is_file()


def load() -> Profile:
    raw = read_yaml(profile_path(), default=None)
    if raw is None:
        return Profile()
    return from_dict(raw)


def save(p: Profile) -> None:
    write_yaml(profile_path(), p.to_dict(), header=_HEADER)


# --- starter profiles offered by the wizard --------------------------------
# Names and descriptions shown to the reader come from the string catalogue;
# only the matching terms live here, because those are data rather than prose.
STARTERS: dict[str, list[dict]] = {
    "tech": [
        {"name": "Artificial intelligence",
         "match": ["artificial intelligence", "machine learning", "large language model",
                   "neural network", "AI model"], "weight": 4},
        {"name": "AI governance and regulation",
         "match": ["AI Act", "AI regulation", "algorithmic accountability", "AI safety policy"],
         "weight": 5},
        {"name": "Semiconductor policy",
         "match": ["export control", "lithography", "semiconductor fab", "ASML", "TSMC"],
         "exclude": ["semiconductor stocks"], "weight": 4},
        {"name": "Open source",
         "match": ["open source", "self-hosted", "federated", "AGPL"], "weight": 3},
    ],
    "world": [
        {"name": "Elections and democracy",
         "match": ["general election", "referendum", "electoral commission", "coalition talks"],
         "weight": 4},
        {"name": "Climate and energy",
         "match": ["emissions", "renewable energy", "grid capacity", "climate policy"],
         "weight": 4},
        {"name": "Trade and sanctions",
         "match": ["tariff", "sanctions", "trade agreement", "export ban"], "weight": 4},
        {"name": "Public health",
         "match": ["outbreak", "vaccination", "public health emergency"], "weight": 3},
    ],
    "security": [
        {"name": "Actively exploited vulnerabilities",
         "match": ["actively exploited", "zero-day", "known exploited", "in the wild"],
         "weight": 5},
        {"name": "Ransomware and intrusion",
         "match": ["ransomware", "data breach", "supply chain attack", "credential theft"],
         "weight": 4},
        {"name": "Critical infrastructure",
         "match": ["power grid", "water utility", "industrial control system", "SCADA"],
         "weight": 4},
        {"name": "Cloud and identity",
         "match": ["identity provider", "single sign-on", "token theft", "privilege escalation"],
         "weight": 3},
    ],
    "blank": [],
}


def starter_profile(key: str, *, language: str = "en") -> Profile:
    raw = {
        "version": 1,
        "interests": STARTERS.get(key, []),
        "places": [],
        "organisations": [],
        "sources": {"boost": {}, "penalty": {}},
        "mute": {"domains": [], "keywords": []},
        "scoring": {"min_score": 1.0, "cap_per_rule": 16.0, "default_half_life_h": 36.0},
    }
    return from_dict(raw)
