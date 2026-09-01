"""Durable full-text storage, written before any relevance decision.

The rule from CONTRIBUTING.md, restated because it is easy to violate by
accident: any code path that fetches article text writes it here *first*.
Discarding on first fetch is irreversible, and a reader who changes their
interests in March should not be punished for what they cared about in January.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from mcpnews.storage.base import BlobStorage, StorageError


def _month_of(published_at: str | None) -> str:
    if published_at:
        try:
            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            return f"{dt.year:04d}/{dt.month:02d}"
        except ValueError:
            pass
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}/{now.month:02d}"


def archive_key(canonical_url: str, published_at: str | None = None) -> str:
    """Monthly partitions keep any one directory listable on every filesystem."""
    digest = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:32]
    return f"{_month_of(published_at)}/{digest}.json"


class Archive:
    """A thin, deliberately boring wrapper over BlobStorage."""

    def __init__(self, storage: BlobStorage):
        self.storage = storage

    def write(self, *, canonical_url: str, original_url: str, title: str, body: str,
              lang: str = "en", published_at: str | None = None,
              source_id: str | None = None) -> str | None:
        """Store the captured text. Returns the reference, or None if it could not.

        A failure here must never stop collection: an article stored without its
        archived copy is still an article, and the alternative is losing the
        whole run because one disk was full.
        """
        key = archive_key(canonical_url, published_at)
        payload = json.dumps({
            "url": canonical_url,
            "original_url": original_url,
            "title": title,
            "body": body,
            "lang": lang,
            "published_at": published_at,
            "source_id": source_id,
            "archived_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, ensure_ascii=False).encode("utf-8")
        try:
            return self.storage.put(key, payload, content_type="application/json")
        except StorageError:
            return None
        except OSError:
            return None

    def read(self, ref: str) -> dict | None:
        try:
            return json.loads(self.storage.get(ref).decode("utf-8"))
        except (StorageError, OSError, ValueError):
            return None
