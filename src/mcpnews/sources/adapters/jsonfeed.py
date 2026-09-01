"""JSON Feed 1.1, and plain JSON APIs described by a small mapping.

Half the useful government and research endpoints are ordinary JSON rather than
JSON Feed. Rather than write an adapter each, the source file describes where
the items live and which fields mean what:

    config:
      items_path: vulnerabilities        # dotted path, or empty for a top-level list
      map: {title: vulnerabilityName, published: dateAdded, id: cveID}
      url_template: "https://example.org/item/{id}"

That is enough for GeoJSON, the CISA catalogue, an Algolia search endpoint and
most of what a reader will want to add themselves.
"""
from __future__ import annotations

import json
from typing import Any

from mcpnews.ingest.extract import strip_html, summarise
from mcpnews.ingest.fetcher import Fetcher
from mcpnews.sources.adapters._dates import parse_date
from mcpnews.sources.base import CandidateItem, FetchResult, SourceAdapter, register
from mcpnews.store.base import SourceRecord, SourceState

_DEFAULT_MAP = {
    "title": "title", "url": "url", "published": "date_published",
    "summary": "summary", "body": "content_text", "id": "id", "lang": "language",
}
_TITLE_KEYS = ("title", "name", "headline", "vulnerabilityName", "place")
_URL_KEYS = ("url", "link", "external_url", "href", "web_url", "id")
_DATE_KEYS = ("date_published", "published", "pubDate", "dateAdded", "created_at",
              "updated", "time", "date")


def _dig(obj: Any, path: str) -> Any:
    """Follow a dotted path, tolerating a missing step rather than raising."""
    for part in (p for p in (path or "").split(".") if p):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit():
            obj = obj[int(part)] if int(part) < len(obj) else None
        else:
            return None
    return obj


def _first(item: dict, mapped: str | None, fallbacks: tuple[str, ...]) -> Any:
    if mapped:
        got = _dig(item, mapped)
        if got not in (None, ""):
            return got
    for key in fallbacks:
        got = _dig(item, key)
        if got not in (None, ""):
            return got
    return None


@register("json_feed")
class JsonFeedAdapter(SourceAdapter):
    label_key = "sources.kind.json_feed"

    async def fetch(self, source: SourceRecord, state: SourceState,
                    fetcher: Fetcher) -> FetchResult:
        url = source.url
        params = (source.config or {}).get("query_params") or {}
        if params:
            joined = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}{'&' if '?' in url else '?'}{joined}"
        r = await fetcher.get(url, etag=state.etag, last_modified=state.last_modified)
        if r.not_modified:
            return FetchResult(not_modified=True, etag=state.etag,
                               last_modified=state.last_modified)
        return FetchResult(items=self.parse(r.text, source), etag=r.headers.get("etag"),
                           last_modified=r.headers.get("last-modified"))

    def parse(self, text: str, source: SourceRecord) -> list[CandidateItem]:
        data = json.loads(text)
        cfg = source.config or {}
        mapping = {**_DEFAULT_MAP, **(cfg.get("map") or {})}
        items_path = cfg.get("items_path")

        if items_path:
            raw_items = _dig(data, items_path)
        elif isinstance(data, list):
            raw_items = data
        elif isinstance(data, dict):
            # JSON Feed calls it "items"; GeoJSON calls it "features"; several
            # search APIs call it "hits" or "results" or "data".
            raw_items = next(
                (data[k] for k in ("items", "features", "hits", "results", "data", "reports")
                 if isinstance(data.get(k), list)), None)
        else:
            raw_items = None
        if not isinstance(raw_items, list):
            return []

        template = cfg.get("url_template")
        out: list[CandidateItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            # GeoJSON and several APIs nest the interesting fields one level down.
            item = {**raw, **raw.get("properties", {})} if isinstance(
                raw.get("properties"), dict) else raw
            if isinstance(item.get("fields"), dict):
                item = {**item, **item["fields"]}

            title = _first(item, mapping.get("title"), _TITLE_KEYS)
            identifier = _first(item, mapping.get("id"), ("id", "objectID", "guid"))
            url = _first(item, mapping.get("url"), _URL_KEYS)
            if template and identifier is not None:
                url = template.format(id=identifier, **{k: v for k, v in item.items()
                                                        if isinstance(v, (str, int, float))})
            if not url or not title:
                continue
            url = str(url)
            if not url.startswith(("http://", "https://")):
                continue

            body = _first(item, mapping.get("body"), ("content_text", "content_html", "body"))
            summary = _first(item, mapping.get("summary"), ("summary", "description", "abstract"))
            out.append(CandidateItem(
                url=url,
                title=strip_html(str(title)),
                published_at=parse_date(_first(item, mapping.get("published"), _DATE_KEYS)),
                lang=_first(item, mapping.get("lang"), ("language", "lang")) or None,
                summary=summarise(strip_html(str(summary))) if summary else "",
                body=strip_html(str(body)) if body else "",
                guid=str(identifier) if identifier is not None else url,
                raw_meta={"source_name": source.name, "topics": source.topics,
                          "region": source.region},
            ))
        return out
