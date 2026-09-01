"""Resolve the configured store backend to a live object."""
from __future__ import annotations

from mcpnews.config.settings import Settings
from mcpnews.store import backends  # noqa: F401  (registers every backend)
from mcpnews.store.base import ArticleStore, get_backend, registered

__all__ = ["open_store", "registered"]


def open_store(settings: Settings) -> ArticleStore:
    cls = get_backend(settings.store.backend)
    if settings.store.backend == "sqlite":
        store = cls(settings.db_path)          # type: ignore[call-arg]
    else:
        store = cls(settings.store.dsn)        # type: ignore[call-arg]
    store.initialise()
    return store
