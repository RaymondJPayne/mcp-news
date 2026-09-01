"""Resolve the configured archive backend to a live object."""
from __future__ import annotations

from mcpnews.config.settings import Settings
from mcpnews.storage import backends  # noqa: F401  (registers every backend)
from mcpnews.storage.base import BlobStorage, get_backend, registered

__all__ = ["open_storage", "registered", "describe_all"]


def open_storage(settings: Settings) -> BlobStorage:
    cls = get_backend(settings.blob.backend)
    if settings.blob.backend == "local":
        return cls(settings.blob_root, **settings.blob.options)  # type: ignore[call-arg]
    return cls(**settings.blob.options)                          # type: ignore[call-arg]


def describe_all() -> list[dict]:
    """What the Settings screen offers, and which options actually work."""
    from mcpnews.storage.backends.local import LocalStorage
    from mcpnews.storage.backends.remote import _Unimplemented

    out = []
    for name in registered():
        cls = get_backend(name)
        out.append({
            "kind": name,
            "implemented": issubclass(cls, LocalStorage),
            "needs_oauth": bool(getattr(cls, "needs_oauth", False))
            if issubclass(cls, _Unimplemented) else False,
        })
    return out
