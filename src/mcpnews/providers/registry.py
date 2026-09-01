"""The provider registry: slots, chains, failover and the capability tier.

Two rules from docs/PROVIDERS.md are enforced here rather than trusted to
callers:

1. The application never talks to a vendor SDK — only to ``ChatProvider`` and
   ``EmbedProvider``.
2. No model is ever required. ``NoProviderAvailable`` means *degrade*, never
   *crash*, and every caller in this codebase treats it that way.
"""
from __future__ import annotations

import logging
from typing import Any

from mcpnews.config.providers import infer_function, load_resolved, slot_is_usable
from mcpnews.providers import adapters  # noqa: F401  (registers every adapter)
from mcpnews.providers.base import get_adapter, registered_kinds
from mcpnews.providers.chain import Chain, FailoverPolicy, NoProviderAvailable

log = logging.getLogger("mcpnews.providers")

__all__ = ["ProviderRegistry", "NoProviderAvailable", "registered_kinds"]

#: Tiers, exactly as docs/PROVIDERS.md §4 defines them.
TIER_COLLECT, TIER_INDEX, TIER_UNDERSTAND = 0, 1, 2


class ProviderRegistry:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config if config is not None else load_resolved()
        self._instances: dict[str, Any] = {}
        self._build()

    # ---- construction ----------------------------------------------------
    def _adapter_class(self, kind: str, function: str):
        """An embed slot prefers ``<kind>_embed`` when the registry has one.

        This is what lets providers.yaml say ``kind: openai_compatible`` for both
        functions, as the documented example does, while the code still gets two
        genuinely different classes.
        """
        if function == "embed":
            try:
                return get_adapter(f"{kind}_embed")
            except KeyError:
                pass
        return get_adapter(kind)

    def _build(self) -> None:
        slots = self.config.get("providers") or {}
        self._slot_config: dict[str, dict] = {}
        self._slot_function: dict[str, str] = {}
        for slot, cfg in slots.items():
            if not isinstance(cfg, dict):
                continue
            self._slot_config[slot] = cfg
            self._slot_function[slot] = infer_function(slot, cfg)

        policy = FailoverPolicy.from_dict(self.config.get("failover"))
        chains_cfg = self.config.get("chains") or {}
        self.chains: dict[str, Chain] = {}
        for name in ("chat", "embed"):
            self.chains[name] = Chain(
                name=name, slots=list(chains_cfg.get(name) or []), policy=policy,
                resolver=self._resolve)

    def _resolve(self, slot: str):
        """A live provider for a slot, or None when it is not usable.

        Not usable covers three cases and treats them identically on purpose: the
        slot is absent, its adapter kind is unknown, or it has no base_url and
        model because the reader never filled them in.
        """
        if slot in self._instances:
            return self._instances[slot]
        cfg = self._slot_config.get(slot)
        if not cfg:
            return None
        if not slot_is_usable(cfg):
            return None
        try:
            cls = self._adapter_class(str(cfg.get("kind", "openai_compatible")),
                                      self._slot_function.get(slot, "chat"))
        except KeyError as exc:
            # An unknown kind is a configuration error worth naming once, not a
            # stack trace at first use.
            log.error("slot %s: %s", slot, exc)
            self._instances[slot] = None
            return None
        instance = cls(cfg, slot)          # type: ignore[call-arg]
        self._instances[slot] = instance
        return instance

    # ---- capability ------------------------------------------------------
    def has_chat(self) -> bool:
        return bool(self.chains["chat"].configured_slots())

    def has_embed(self) -> bool:
        return bool(self.chains["embed"].configured_slots())

    def tier(self) -> int:
        if self.has_embed() and self.has_chat():
            return TIER_UNDERSTAND
        if self.has_embed():
            return TIER_INDEX
        return TIER_COLLECT

    def health(self) -> list[dict]:
        out: list[dict] = []
        for name, chain in self.chains.items():
            for entry in chain.health():
                out.append({**entry, "chain": name,
                            "function": self._slot_function.get(entry["slot"], name)})
        return out

    # ---- operations ------------------------------------------------------
    async def chat(self, messages: list[dict], *, schema: dict | None = None,
                   max_tokens: int | None = None) -> tuple[str, str]:
        async def op(provider, slot):
            return await provider.chat(messages, schema=schema, max_tokens=max_tokens)
        return await self.chains["chat"].run(op)

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], str, str]:
        """Returns (vectors, slot, model_id).

        The model id travels with the vectors because vectors from different
        models are not comparable, and the store refuses to mix them in one
        index. Failing over mid-corpus writes a second vector space rather than
        silently corrupting the first.
        """
        holder: dict[str, str] = {}

        async def op(provider, slot):
            holder["model_id"] = provider.model_id
            return await provider.embed(texts)

        vectors, slot = await self.chains["embed"].run(op)
        return vectors, slot, holder.get("model_id", "")

    async def probe_all(self) -> None:
        for chain in self.chains.values():
            await chain.probe()

    async def test_slot(self, slot: str) -> bool:
        provider = self._resolve(slot)
        if provider is None:
            return False
        try:
            return bool(await provider.health())
        except Exception:
            return False
