"""MySQL / MariaDB backend — interface only, not yet implemented.

The translation is the same shape as the PostgreSQL note, with two differences
worth recording before anyone starts: MySQL full-text indexes are per-table
rather than a separate virtual table, so ``keyword_search`` uses
``MATCH … AGAINST`` on the articles table directly and builds its own snippet;
and ``INSERT … ON DUPLICATE KEY UPDATE`` replaces ``ON CONFLICT``.
"""
from __future__ import annotations

from mcpnews.store.base import ArticleStore, register

_MESSAGE = (
    "The MySQL store backend is not implemented in this release. "
    "Set store.backend to 'sqlite' in config/settings.yaml, or from the Storage "
    "section of the Settings screen."
)


@register("mysql")
class MySQLStore(ArticleStore):
    def __init__(self, dsn: str):
        raise NotImplementedError(_MESSAGE)

    def __getattr__(self, item: str):
        raise NotImplementedError(_MESSAGE)


# Declared complete on purpose. The constructor never returns, so the missing
# methods are unreachable; clearing the abstract set means a reader who selects
# this backend gets the sentence above rather than a TypeError listing thirty
# method names. ABCMeta populates this after the class body, so it is cleared
# here rather than inside it.
MySQLStore.__abstractmethods__ = frozenset()
