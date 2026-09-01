"""Chains, breakers and the failure classification that decides when to fail over."""
from __future__ import annotations

import asyncio

import pytest

from mcpnews.providers.chain import Breaker, Chain, FailoverPolicy, NoProviderAvailable
from mcpnews.providers.errors import (
    ProviderRequestError,
    ProviderUnavailable,
    classify_status,
)
from mcpnews.providers.registry import ProviderRegistry


class FakeProvider:
    """No network, no key, no cost. What every provider test runs against."""

    def __init__(self, *, fail: int = 0, always_fail: bool = False, bad_request: bool = False):
        self.calls = 0
        self.fail = fail
        self.always_fail = always_fail
        self.bad_request = bad_request
        self.model_id = "fake@8"

    async def chat(self, messages, **_kw):
        self.calls += 1
        if self.bad_request:
            raise ProviderRequestError("malformed")
        if self.always_fail or self.calls <= self.fail:
            raise ProviderUnavailable("down")
        return "answer"

    async def embed(self, texts):
        self.calls += 1
        if self.always_fail:
            raise ProviderUnavailable("down")
        return [[0.1, 0.2] for _ in texts]

    async def health(self):
        return not self.always_fail


def chain_of(providers: dict, **policy) -> Chain:
    return Chain(name="chat", slots=list(providers),
                 policy=FailoverPolicy(backoff_initial_s=0, **policy),
                 resolver=providers.get)


@pytest.mark.parametrize("status,expected", [
    (200, None), (301, None),
    (400, ProviderRequestError), (401, ProviderRequestError), (404, ProviderRequestError),
    (408, ProviderUnavailable), (429, ProviderUnavailable),
    (500, ProviderUnavailable), (503, ProviderUnavailable),
])
def test_failure_classification(status, expected):
    assert classify_status(status) is expected


def test_chain_uses_the_first_healthy_slot():
    providers = {"local": FakeProvider(), "cloud": FakeProvider()}
    result, slot = asyncio.run(
        chain_of(providers).run(lambda p, s: p.chat([])))
    assert result == "answer" and slot == "local"
    assert providers["cloud"].calls == 0


def test_chain_fails_over_and_opens_the_breaker():
    providers = {"local": FakeProvider(always_fail=True), "cloud": FakeProvider()}
    chain = chain_of(providers, max_attempts_per_slot=2, open_after_failures=1)
    _answer, slot = asyncio.run(chain.run(lambda p, s: p.chat([])))
    assert slot == "cloud"
    assert providers["local"].calls == 2          # retried, then given up on
    assert chain.breakers["local"].state == "open"

    # With the breaker open the dead slot is skipped entirely.
    providers["local"].calls = 0
    asyncio.run(chain.run(lambda p, s: p.chat([])))
    assert providers["local"].calls == 0


def test_a_bad_request_does_not_fail_over_or_trip_the_breaker():
    """Our bug. Retrying it against a paid provider would just cost money twice."""
    providers = {"local": FakeProvider(bad_request=True), "cloud": FakeProvider()}
    chain = chain_of(providers)
    with pytest.raises(ProviderRequestError):
        asyncio.run(chain.run(lambda p, s: p.chat([])))
    assert providers["cloud"].calls == 0
    assert chain.breakers["local"].state == "closed"


def test_exhausted_chain_raises_the_degrade_signal():
    providers = {"local": FakeProvider(always_fail=True), "cloud": FakeProvider(always_fail=True)}
    with pytest.raises(NoProviderAvailable):
        asyncio.run(chain_of(providers, max_attempts_per_slot=1).run(lambda p, s: p.chat([])))


def test_transient_failure_recovers_within_one_slot():
    providers = {"local": FakeProvider(fail=1)}
    result, _ = asyncio.run(chain_of(providers, max_attempts_per_slot=2).run(
        lambda p, s: p.chat([])))
    assert result == "answer"


def test_breaker_transitions():
    breaker = Breaker(open_after=2, cooldown_s=0)
    assert breaker.state == "closed"
    breaker.record_failure("a")
    assert breaker.state == "closed"
    breaker.record_failure("b")
    assert breaker.state in ("open", "half_open")   # zero cooldown reopens immediately
    breaker.record_success()
    assert breaker.state == "closed" and breaker.failures == 0


def test_tier_zero_when_nothing_is_configured():
    registry = ProviderRegistry({"providers": {}, "chains": {"chat": [], "embed": []}})
    assert registry.tier() == 0
    assert [h["state"] for h in registry.health()] == []


def test_tiers_track_configured_slots(monkeypatch):
    config = {
        "providers": {
            "local_embed": {"kind": "openai_compatible", "function": "embed",
                            "base_url": "http://localhost:1", "model": "m"},
            "local_chat": {"kind": "openai_compatible", "function": "chat",
                           "base_url": "", "model": "m"},
        },
        "chains": {"chat": ["local_chat"], "embed": ["local_embed"]},
    }
    assert ProviderRegistry(config).tier() == 1        # embed only
    config["providers"]["local_chat"]["base_url"] = "http://localhost:2"
    assert ProviderRegistry(config).tier() == 2


def test_a_cloud_slot_without_its_key_is_not_configured(monkeypatch):
    """Otherwise a fresh install claims Tier 2 it cannot deliver."""
    monkeypatch.delenv("CLOUD_CHAT_API_KEY", raising=False)
    config = {"providers": {"cloud_chat": {
        "kind": "openai_compatible", "function": "chat",
        "base_url": "https://api.example.com/v1", "model": "m",
        "api_key_env": "CLOUD_CHAT_API_KEY", "requires_api_key": True}},
        "chains": {"chat": ["cloud_chat"], "embed": []}}
    assert ProviderRegistry(config).tier() == 0
    monkeypatch.setenv("CLOUD_CHAT_API_KEY", "sk-test")
    assert ProviderRegistry(config).has_chat() is True


def test_unknown_adapter_kind_is_reported_not_crashed(caplog):
    config = {"providers": {"x": {"kind": "no_such_engine", "base_url": "http://h",
                                  "model": "m"}},
              "chains": {"chat": ["x"], "embed": []}}
    registry = ProviderRegistry(config)
    assert registry.tier() == 0
    assert registry.chains["chat"].configured_slots() == []
