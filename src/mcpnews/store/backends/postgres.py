"""PostgreSQL backend — interface only, not yet implemented.

Kept in the tree because the shape of ``ArticleStore`` has to be checked against
a second, genuinely different database or it quietly becomes a description of
SQLite. Every method below has a straightforward translation:

* ``articles.id``            -> ``BIGSERIAL PRIMARY KEY``
* FTS5                       -> ``tsvector`` column with a GIN index; ``bm25()``
                                becomes ``ts_rank_cd`` and ``snippet()`` becomes
                                ``ts_headline``
* the simhash band columns   -> four ``INTEGER`` columns with B-tree indexes,
                                identical query
* ``INSERT … ON CONFLICT``   -> identical syntax
* ``article_vectors.vector`` -> ``pgvector`` when available, ``BYTEA`` otherwise

Nothing in the interface needs to change to accommodate it, which was the point.
"""
from __future__ import annotations

from mcpnews.store.base import ArticleStore, register

_MESSAGE = (
    "The PostgreSQL store backend is not implemented in this release. "
    "Set store.backend to 'sqlite' in config/settings.yaml, or from the Storage "
    "section of the Settings screen. See docs/ARCHITECTURE.md."
)


@register("postgres")
class PostgresStore(ArticleStore):
    def __init__(self, dsn: str):
        raise NotImplementedError(_MESSAGE)

    # The abstract methods are satisfied by the constructor never returning.
    def __getattr__(self, item: str):
        raise NotImplementedError(_MESSAGE)
