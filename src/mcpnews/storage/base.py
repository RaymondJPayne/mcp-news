"""Blob storage for the article archive.

The archive is written *before* any relevance decision is taken, because what is
not captured on first fetch is often gone within weeks. That makes durable,
swappable storage a structural concern rather than a nicety.

Design constraints this interface has to satisfy, all of them present from the
start because retrofitting any of them is expensive:

* **Keys are logical, not filesystem paths.** Always ``/``-separated, always
  relative, never absolute, never containing ``..``. A backend maps them onto
  whatever it uses — a directory, an object key, a Drive folder id.
* **The root may live outside the container.** A bind-mounted host directory on
  Windows, macOS or Linux is the normal case, not the exception, so nothing here
  assumes a POSIX path, a mount point, or that the process can create the root.
* **Remote backends are possible without changing callers.** Every operation is
  whole-blob and idempotent; there is no seek, no append, no directory
  semantics, and no assumption that listing is cheap.
* **Failure is reportable in plain language.** ``health()`` returns a message key
  from the string catalogue, so the Settings screen can explain the problem to a
  reader who has never heard of a bind mount.
"""
from __future__ import annotations

import posixpath
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass

_REGISTRY: dict[str, type[BlobStorage]] = {}


def register(name: str) -> Callable[[type], type]:
    def deco(cls: type) -> type:
        _REGISTRY[name] = cls  # type: ignore[assignment]
        return cls
    return deco


def get_backend(name: str) -> type[BlobStorage]:
    if name not in _REGISTRY:
        raise KeyError(f"unknown storage backend {name!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def registered() -> list[str]:
    return sorted(_REGISTRY)


class StorageError(RuntimeError):
    """Carries a catalogue key so the reason can be shown in the reader's language."""

    def __init__(self, message_key: str, detail: str = ""):
        super().__init__(detail or message_key)
        self.message_key = message_key
        self.detail = detail


def normalise_key(key: str) -> str:
    """Reject anything that could escape the storage root.

    Called by every backend. A malformed key is a bug in our code, not user
    input, but the archive is the one thing that cannot be re-created.
    """
    key = key.strip().replace("\\", "/").lstrip("/")
    if not key:
        raise StorageError("err.generic", "empty storage key")
    normalised = posixpath.normpath(key)
    if normalised.startswith(("..", "/")):
        raise StorageError("err.generic", f"unsafe storage key {key!r}")
    return normalised


@dataclass
class Usage:
    blobs: int
    bytes: int


class BlobStorage(ABC):
    """Whole-blob, idempotent, location-agnostic."""

    #: Shown in the UI so a reader can see where their archive actually is.
    kind: str = "base"

    @abstractmethod
    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream",
            metadata: dict[str, str] | None = None) -> str:
        """Write a blob and return the reference stored alongside the article."""

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def list(self, prefix: str = "") -> Iterable[str]: ...

    @abstractmethod
    def usage(self) -> Usage: ...

    @abstractmethod
    def describe(self) -> dict:
        """Human-facing location and configuration, with no secrets in it."""

    @abstractmethod
    def health(self) -> tuple[bool, str]:
        """(reachable, message_key). An empty key means no problem to report."""
