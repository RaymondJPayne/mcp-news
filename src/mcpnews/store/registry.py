"""Resolve the configured store backend to a live object."""
from __future__ import annotations

from mcpnews.config.settings import Settings
from mcpnews.store import backends  # noqa: F401  (registers every backend)
from mcpnews.store.base import ArticleStore, get_backend, registered

__all__ = ["open_store", "registered"]


def open_store(settings: Settings) -> ArticleStore:
    cls = get_backend(settings.store.backend)
    # SQLite is addressed by a path we derive; every other backend by a DSN the
    # reader supplied. Backends other than SQLite raise on construction today.
    target = settings.db_path if settings.store.backend == "sqlite" else settings.store.dsn
    store = cls(target)                        # type: ignore[call-arg]
    store.initialise()
    return store
