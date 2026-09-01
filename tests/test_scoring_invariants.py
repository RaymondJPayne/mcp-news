"""These tests exist to stop a specific regression.

If someone applies recency decay inside the scorer, historical articles score
near zero no matter how well they match, and every backfill silently produces
an empty result set. It is an easy mistake to make and a hard one to notice.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mcpnews.config.profile import from_dict
from mcpnews.rank.scorer import CompiledProfile, score
from mcpnews.search.views import decay_factor, display_score

PROFILE = from_dict({
    "version": 1,
    "interests": [
        {"name": "Semiconductor policy",
         "match": ["export control", "lithography", "ASML"], "weight": 5,
         "in_title_multiplier": 2.0},
        {"name": "Open source", "match": ["open source"], "weight": 2},
    ],
    "places": [{"name": "Brazil", "match": ["Brazil", "Brasilia"], "weight": 4}],
    "sources": {"boost": {"reuters.com": 1.5}, "penalty": {"aggregator.example": 0.5}},
    "mute": {"domains": ["clickbait.example"], "keywords": ["horoscope"]},
    "scoring": {"min_score": 1.0, "cap_per_rule": 16.0, "default_half_life_h": 36},
})

TITLE = "New export control rules hit lithography suppliers"
BODY = "The export control regime covers lithography tooling sold into Brazil."


def test_score_is_independent_of_publication_date():
    """The same article must score identically whether it is an hour or a year old."""
    compiled = CompiledProfile(PROFILE)
    a = compiled.score(TITLE, BODY, "example.com", {})
    b = compiled.score(TITLE, BODY, "example.com", {})
    assert a.total == b.total

    # And the scorer has no way to know a date even if someone passed one.
    recent = datetime.now(UTC)
    old = recent - timedelta(days=400)
    for published in (recent, old):
        result = compiled.score(TITLE, BODY, "example.com",
                                {"published_at": published.isoformat()})
        assert result.total == a.total

    # Freshness is a view. Same stored score, different lens.
    assert display_score(a.total, recent.isoformat(), 36) > display_score(
        a.total, old.isoformat(), 36)
    assert display_score(a.total, old.isoformat(), None) == pytest.approx(a.total)


def test_tier_zero_scoring_needs_no_provider():
    """Scoring must work with no chat or embed provider configured at all."""
    from mcpnews.providers.registry import ProviderRegistry

    registry = ProviderRegistry({"providers": {}, "chains": {"chat": [], "embed": []}})
    assert registry.tier() == 0
    assert not registry.has_chat() and not registry.has_embed()

    result = score(TITLE, BODY, "example.com", {}, PROFILE)
    assert result.total > 0
    assert any(r.name == "Semiconductor policy" for r in result.rules)


def test_word_boundaries_are_respected():
    profile = from_dict({"interests": [{"name": "Ace", "match": ["Ace"], "weight": 5}]})
    compiled = CompiledProfile(profile)
    assert compiled.score("Peace in space on the surface", "", "x.com", {}).total == 0
    assert compiled.score("Ace wins", "", "x.com", {}).total > 0


def test_title_multiplier_beats_a_body_mention():
    compiled = CompiledProfile(PROFILE)
    in_title = compiled.score("ASML news", "unrelated words", "x.com", {})
    in_body = compiled.score("unrelated words", "ASML news", "x.com", {})
    assert in_title.total == pytest.approx(in_body.total * 2.0)
    assert in_title.rules[0].in_title is True


def test_cap_per_rule_stops_one_rule_dominating():
    body = " ".join(["ASML"] * 50)
    compiled = CompiledProfile(PROFILE)
    result = compiled.score("neutral headline", body, "x.com", {})
    assert result.total == pytest.approx(PROFILE.scoring.cap_per_rule)


def test_must_include_gates_the_rule():
    profile = from_dict({"interests": [
        {"name": "Apple", "match": ["Apple"], "must_include": ["technology"], "weight": 5}]})
    compiled = CompiledProfile(profile)
    assert compiled.score("Apple harvest season", "orchards", "x.com", {}).total == 0
    assert compiled.score("Apple ships technology", "", "x.com", {}).total > 0


def test_exclude_suppresses_the_rule():
    compiled = CompiledProfile(from_dict({"interests": [
        {"name": "Chips", "match": ["chips"], "exclude": ["potato"], "weight": 5}]}))
    assert compiled.score("Potato chips recalled", "", "x.com", {}).total == 0
    assert compiled.score("Memory chips shipped", "", "x.com", {}).total > 0


def test_mute_by_domain_and_keyword_zeroes_everything():
    compiled = CompiledProfile(PROFILE)
    muted_domain = compiled.score(TITLE, BODY, "clickbait.example", {})
    assert muted_domain.total == 0 and muted_domain.muted

    muted_word = compiled.score(TITLE, BODY + " your horoscope today", "example.com", {})
    assert muted_word.total == 0 and muted_word.muted


def test_source_boost_and_penalty_multiply_the_total():
    compiled = CompiledProfile(PROFILE)
    plain = compiled.score(TITLE, BODY, "example.com", {})
    boosted = compiled.score(TITLE, BODY, "reuters.com", {})
    penalised = compiled.score(TITLE, BODY, "aggregator.example", {})
    assert boosted.total == pytest.approx(plain.total * 1.5)
    assert penalised.total == pytest.approx(plain.total * 0.5)
    # A subdomain of a boosted domain is boosted too.
    assert compiled.score(TITLE, BODY, "uk.reuters.com", {}).total == pytest.approx(
        boosted.total)


def test_matched_rules_explain_the_score():
    result = score(TITLE, BODY, "example.com", {}, PROFILE)
    assert "Semiconductor policy" in result.explain()
    assert sum(r.points for r in result.rules) == pytest.approx(result.total)


def test_decay_factor_halves_at_the_half_life():
    assert decay_factor(36, 36) == pytest.approx(0.5)
    assert decay_factor(0, 36) == pytest.approx(1.0)
    assert decay_factor(1000, 0) == 1.0
