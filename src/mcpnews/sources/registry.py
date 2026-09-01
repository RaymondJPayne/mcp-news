"""Adapter lookup, plus the sniffing the "add a source" screen needs."""
from __future__ import annotations

from mcpnews.sources import adapters  # noqa: F401  (registers every adapter)
from mcpnews.sources.base import SourceAdapter, get_adapter, registered

__all__ = ["get_adapter", "registered", "adapter_for", "sniff_kind"]


def adapter_for(kind: str) -> SourceAdapter:
    return get_adapter(kind)()


def sniff_kind(text: str, content_type: str = "") -> str | None:
    """Guess a feed's kind from its first bytes, so the reader need not know.

    Returns None when nothing is recognisable, which the caller reports as
    "that responded, but it is not a feed".
    """
    head = (text or "")[:4000].lstrip("﻿ \t\r\n")
    ct = (content_type or "").lower()
    if head.startswith(("{", "[")) or "json" in ct:
        return "json_feed"
    lowered = head.lower()
    if "<feed" in lowered:
        return "atom"
    if "<rss" in lowered or "<rdf:rdf" in lowered:
        return "rss"
    if "<urlset" in lowered or "<sitemapindex" in lowered:
        return "sitemap"
    if lowered.startswith("<?xml") and "<channel" in lowered:
        return "rss"
    return None
