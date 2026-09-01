"""Storage interface for sources, fetch state and articles.

One backend ships and works: SQLite, a single file, no services. The interface
is written so a PostgreSQL or MySQL adapter is a matter of writing SQL rather
than reshaping the pipeline — no method here leaks a SQLite type, a cursor
object, a rowid trick or a connection.

Two boundaries are load-bearing:

* The *file* owns a source's intent (url, kind, lifecycle dates). The *database*
  owns its fetch state and, once registered, its status. See docs/SOURCES.md §3.
* ``interest_score`` is interest only. Recency is applied by the caller through
  ``search/views.py`` and is never written back.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

ENRICHMENT_CAPABILITIES = ("embedded", "translated", "contextual", "entities")

_REGISTRY: dict[str, type[ArticleStore]] = {}


def register(name: str) -> Callable[[type], type]:
    def deco(cls: type) -> type:
        _REGISTRY[name] = cls  # type: ignore[assignment]
        return cls
    return deco


def get_backend(name: str) -> type[ArticleStore]:
    if name not in _REGISTRY:
        raise KeyError(f"unknown store backend {name!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def registered() -> list[str]:
    return sorted(_REGISTRY)


@dataclass
class SourceRecord:
    id: str
    name: str
    kind: str
    url: str
    lang: str = "en"
    region: str = "global"
    topics: list[str] = field(default_factory=list)
    interval_min: int = 60
    status: str = "active"           # active | paused | deprecated | dead
    added: str | None = None
    verified: str | None = None
    expires: str | None = None
    replaced_by: str | None = None
    notes: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    auth: dict[str, Any] = field(default_factory=dict)
    bundle: str = "local"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "kind": self.kind, "url": self.url,
            "lang": self.lang, "region": self.region, "topics": list(self.topics),
            "interval_min": self.interval_min, "status": self.status,
            "added": self.added, "verified": self.verified, "expires": self.expires,
            "replaced_by": self.replaced_by, "notes": self.notes,
            "config": dict(self.config), "auth": dict(self.auth), "bundle": self.bundle,
        }


@dataclass
class SourceState:
    source_id: str
    cursor: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    last_run_at: str | None = None
    last_ok_at: str | None = None
    consecutive_failures: int = 0
    last_error: str | None = None
    next_allowed_at: str | None = None
    article_count: int = 0


@dataclass
class ArticleRecord:
    url: str                     # canonical
    original_url: str
    domain: str
    title: str
    source_id: str | None = None
    body: str = ""
    summary: str = ""
    lang: str = "en"
    published_at: str | None = None
    fetched_at: str | None = None
    simhash: int = 0
    cluster_id: int | None = None
    interest_score: float = 0.0
    matched_rules: list[dict] = field(default_factory=list)
    scored_at: str | None = None
    archive_ref: str | None = None
    title_translated: str | None = None
    id: int | None = None
    enrichment: dict[str, str] = field(
        default_factory=lambda: dict.fromkeys(ENRICHMENT_CAPABILITIES, "pending"))

    def to_dict(self, *, include_body: bool = False) -> dict:
        d = {
            "article_id": self.id, "url": self.url, "original_url": self.original_url,
            "domain": self.domain, "title": self.title,
            "title_translated": self.title_translated, "summary": self.summary,
            "lang": self.lang, "published_at": self.published_at,
            "fetched_at": self.fetched_at, "source_id": self.source_id,
            "interest_score": round(self.interest_score, 3),
            "matched_rules": self.matched_rules, "cluster_id": self.cluster_id,
            "archive_ref": self.archive_ref, "enrichment_state": dict(self.enrichment),
        }
        if include_body:
            d["body"] = self.body
        return d


class ArticleStore(ABC):
    """Everything the pipeline, the API and the MCP server need from storage."""

    # ---- lifecycle -------------------------------------------------------
    @abstractmethod
    def initialise(self) -> None:
        """Create or migrate the schema. Safe to call on every start."""

    @abstractmethod
    def close(self) -> None: ...

    # ---- key/value, for small pieces of state that are not worth a table --
    @abstractmethod
    def get_meta(self, key: str, default: str | None = None) -> str | None: ...

    @abstractmethod
    def set_meta(self, key: str, value: str) -> None: ...

    # ---- sources ---------------------------------------------------------
    @abstractmethod
    def upsert_source(self, source: SourceRecord) -> bool:
        """Register or refresh a source from its file.

        Returns True when the source is new. Implementations MUST NOT overwrite
        an existing row's ``status`` — the reader can toggle sources in the
        dashboard, and a container restart must not resurrect what they
        switched off. docs/SOURCES.md §3.
        """

    @abstractmethod
    def set_source_status(self, source_id: str, status: str) -> None: ...

    @abstractmethod
    def delete_source(self, source_id: str) -> None: ...

    @abstractmethod
    def get_source(self, source_id: str) -> SourceRecord | None: ...

    @abstractmethod
    def list_sources(self, status: str | None = None) -> list[SourceRecord]: ...

    @abstractmethod
    def get_source_state(self, source_id: str) -> SourceState: ...

    @abstractmethod
    def save_source_state(self, state: SourceState) -> None: ...

    @abstractmethod
    def due_sources(self, now_iso: str) -> list[SourceRecord]:
        """Active or deprecated sources whose politeness window has elapsed."""

    # ---- articles --------------------------------------------------------
    @abstractmethod
    def find_by_url(self, canonical_url: str) -> int | None: ...

    @abstractmethod
    def insert_article(self, article: ArticleRecord) -> int: ...

    @abstractmethod
    def get_article(self, article_id: int) -> ArticleRecord | None: ...

    @abstractmethod
    def update_score(self, article_id: int, score: float, rules: list[dict],
                     scored_at: str) -> None: ...

    @abstractmethod
    def set_enrichment(self, article_id: int, capability: str, state: str) -> None: ...

    @abstractmethod
    def near_duplicate(self, simhash: int, *, within_days: int = 7,
                       max_distance: int | None = None) -> int | None:
        """The id of an existing near-identical article, or None."""

    @abstractmethod
    def iter_articles(self, *, batch: int = 500) -> Iterable[ArticleRecord]:
        """Every article, for a full re-score after a profile edit."""

    # ---- reading ---------------------------------------------------------
    @abstractmethod
    def feed(self, *, hours: int, limit: int, min_score: float,
             half_life_h: float | None) -> list[ArticleRecord]:
        """The ranked feed. Decay is applied here as a view, never stored."""

    @abstractmethod
    def keyword_search(self, query: str, *, limit: int = 20, days: int | None = 90,
                       lang: str | None = None) -> list[tuple[ArticleRecord, float, str]]:
        """Returns (article, relevance, snippet)."""

    @abstractmethod
    def timeline(self, term: str, *, days: int = 90,
                 bucket: str = "day") -> list[tuple[str, int]]: ...

    @abstractmethod
    def counts(self) -> dict[str, int]:
        """articles, enriched, queued, sources_active, sources_failing."""

    # ---- vectors ---------------------------------------------------------
    # Optional: a backend may raise NotImplementedError and the system stays at
    # Tier 0, which is a supported state rather than a failure.
    @abstractmethod
    def pending_embedding(self, limit: int = 100) -> list[ArticleRecord]:
        """Articles awaiting an embedding, highest interest score first.

        Relevance order matters: a reader who configures a model after collecting
        for a month wants the things they care about processed first, not the
        oldest thing in the database.
        """

    @abstractmethod
    def save_vector(self, article_id: int, model_id: str, vector: list[float]) -> None: ...

    @abstractmethod
    def vector_search(self, vector: list[float], model_id: str, *, limit: int = 20,
                      days: int | None = 90) -> list[tuple[ArticleRecord, float]]:
        """Nearest neighbours within one model's vector space, never across two."""

    @abstractmethod
    def vector_spaces(self) -> list[tuple[str, int]]:
        """(model_id, count) for every space present. Used by the Status screen."""
