"""Retrieval interfaces.

Keyword retrieval is always available. Semantic and hybrid retrieval activate
when an embedding provider is configured; callers ask for ``auto`` and are told
in the response which mode actually ran, so a degraded answer is never disguised
as a good one.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

Mode = str  # "auto" | "keyword" | "semantic" | "hybrid"


@dataclass
class SearchHit:
    article_id: int
    title: str
    url: str
    domain: str
    published_at: str | None
    score: float
    snippet: str = ""
    title_translated: str | None = None

    def to_dict(self) -> dict:
        return {
            "article_id": self.article_id,
            "title": self.title,
            "title_translated": self.title_translated,
            "url": self.url,
            "domain": self.domain,
            "published_at": self.published_at,
            "score": round(self.score, 4),
            "snippet": self.snippet,
        }


@dataclass
class SearchResult:
    hits: list[SearchHit]
    mode: Mode
    #: Set when the requested mode was unavailable, so the UI can say why.
    note_key: str | None = None


class SearchBackend(ABC):
    @abstractmethod
    def keyword(self, query: str, *, limit: int = 20, days: int | None = 90,
                lang: str | None = None) -> list[SearchHit]: ...

    @abstractmethod
    def semantic(self, vector: list[float], model_id: str, *, limit: int = 20,
                 days: int | None = 90) -> list[SearchHit]: ...
