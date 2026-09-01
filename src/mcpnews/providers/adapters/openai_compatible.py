"""One adapter, every engine worth supporting.

llama.cpp, Ollama, LM Studio, vLLM, TEI, Infinity, OpenAI, Groq, Mistral,
OpenRouter, Together and most of the rest speak the same two endpoints. Writing
one adapter against ``/chat/completions`` and ``/embeddings`` covers all of them
and keeps the application's only dependency on a *protocol* rather than on a
vendor SDK.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from mcpnews.providers.base import ChatProvider, EmbedProvider, register
from mcpnews.providers.errors import ProviderUnavailable, raise_for_status


class _Base:
    def __init__(self, cfg: dict[str, Any], slot: str = ""):
        self.slot = slot
        self.cfg = cfg or {}
        self.base_url = str(self.cfg.get("base_url") or "").rstrip("/")
        self.model = str(self.cfg.get("model") or "")
        self.timeout_s = float(self.cfg.get("timeout_s", 30))
        key_env = self.cfg.get("api_key_env")
        self.api_key = os.environ.get(str(key_env), "").strip() if key_env else ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _post(self, path: str, payload: dict) -> dict:
        if not self.configured:
            raise ProviderUnavailable(f"{self.slot}: base_url or model is not set")
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(url, json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{self.slot}: {exc}") from exc
        raise_for_status(r.status_code, r.text, slot=self.slot)
        try:
            return r.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"{self.slot}: response was not JSON") from exc

    async def health(self) -> bool:
        """Cheap liveness probe. Must not cost money — a model list is free."""
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout_s, 10)) as client:
                r = await client.get(f"{self.base_url}/models", headers=self._headers())
            return r.status_code < 500
        except httpx.HTTPError:
            return False


@register("openai_compatible")
class OpenAICompatibleChat(_Base, ChatProvider):
    async def chat(self, messages: list[dict], *, schema: dict | None = None,
                   max_tokens: int | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": int(max_tokens or self.cfg.get("max_tokens", 1024)),
            "temperature": float(self.cfg.get("temperature", 0.2)),
            "stream": False,
        }
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": schema, "strict": True},
            }
        # Reasoning models bill thinking tokens against the decode budget and then
        # discard them. Off unless the reader turned it on deliberately.
        if str(self.cfg.get("reasoning", "off")).lower() in ("off", "false", "no", "none"):
            payload["reasoning_effort"] = "none"

        data = await self._post("/chat/completions", payload)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailable(f"{self.slot}: unexpected response shape") from exc


@register("openai_compatible_embed")
class OpenAICompatibleEmbed(_Base, EmbedProvider):
    def __init__(self, cfg: dict[str, Any], slot: str = ""):
        super().__init__(cfg, slot)
        self.dimensions = int(self.cfg.get("dimensions", 0))
        self.batch_size = int(self.cfg.get("batch_size", 32))

    @property
    def model_id(self) -> str:  # type: ignore[override]
        """Vectors from different models are not comparable; the store keys on this."""
        return f"{self.model}@{self.dimensions or 'auto'}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), max(1, self.batch_size)):
            batch = texts[start:start + max(1, self.batch_size)]
            data = await self._post("/embeddings", {"model": self.model, "input": batch})
            try:
                rows = sorted(data["data"], key=lambda d: d.get("index", 0))
                out.extend([float(x) for x in row["embedding"]] for row in rows)
            except (KeyError, TypeError) as exc:
                raise ProviderUnavailable(f"{self.slot}: unexpected embedding shape") from exc
        if out and not self.dimensions:
            self.dimensions = len(out[0])
        return out
