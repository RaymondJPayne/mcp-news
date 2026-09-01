"""Provider interfaces and the registry.

The application talks only to ChatProvider and EmbedProvider. Every engine —
local or cloud — is an adapter behind one of them. See docs/PROVIDERS.md.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Callable

_REGISTRY: dict[str, type] = {}


def register(kind: str) -> Callable[[type], type]:
    """Register an adapter under the `kind` used in providers.yaml."""
    def deco(cls: type) -> type:
        _REGISTRY[kind] = cls
        return cls
    return deco


def get_adapter(kind: str) -> type:
    if kind not in _REGISTRY:
        raise KeyError(f"unknown provider kind {kind!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[kind]


def registered_kinds() -> list[str]:
    return sorted(_REGISTRY)


class ProviderUnavailable(Exception):
    """Transient. Trips the circuit breaker and triggers failover."""


class ProviderRequestError(Exception):
    """Our fault — a malformed request. Must NOT trip the breaker or fail over,
    because the next provider would reject it identically and cost money."""


class ChatProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict], *, schema: dict | None = None,
                   max_tokens: int | None = None) -> str: ...

    @abstractmethod
    async def health(self) -> bool:
        """Cheap liveness probe. Must not cost money."""


class EmbedProvider(ABC):
    #: Vectors from different models are not comparable. The store keys on this.
    model_id: str
    dimensions: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    async def health(self) -> bool: ...
