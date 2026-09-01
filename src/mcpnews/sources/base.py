"""Source adapters: feed in, candidates out.

An adapter fetches one endpoint and returns candidates. It never writes to the
database, never scores, never deduplicates and never calls a model. That
boundary is why adapters stay short enough to contribute in an afternoon and
testable with a fixture file and no network.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from mcpnews.ingest.fetcher import Fetcher
from mcpnews.store.base import SourceRecord, SourceState

_REGISTRY: dict[str, type["SourceAdapter"]] = {}


def register(kind: str) -> Callable[[type], type]:
    def deco(cls: type) -> type:
        _REGISTRY[kind] = cls  # type: ignore[assignment]
        return cls
    return deco


def get_adapter(kind: str) -> type["SourceAdapter"]:
    if kind not in _REGISTRY:
        raise KeyError(f"unknown source kind {kind!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[kind]


def registered() -> list[str]:
    return sorted(_REGISTRY)


@dataclass
class CandidateItem:
    """Not yet an article. No decision has been taken about it."""
    url: str
    title: str
    published_at: str | None = None
    lang: str | None = None
    summary: str = ""
    body: str = ""            # set only when the feed itself carried full text
    guid: str | None = None
    raw_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    items: list[CandidateItem] = field(default_factory=list)
    cursor: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


class SourceAdapter(ABC):
    """One endpoint, one parse. Stateless between calls."""

    #: Shown in the "add a source" screen so the list of types is never hardcoded.
    label_key: str = "sources.kind.rss"

    @abstractmethod
    async def fetch(self, source: SourceRecord, state: SourceState,
                    fetcher: Fetcher) -> FetchResult: ...

    @abstractmethod
    def parse(self, text: str, source: SourceRecord) -> list[CandidateItem]:
        """Parse a payload already in hand. Kept separate from fetching so the
        dashboard can test a feed, and so tests need no network."""
