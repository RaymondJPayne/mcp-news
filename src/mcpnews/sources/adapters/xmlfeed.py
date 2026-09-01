"""RSS 2.0, RDF and Atom 1.0.

Parsed with the standard library rather than a third-party feed parser. The two
formats differ in about a dozen element names and nothing else that matters to a
candidate, and owning the parse keeps the dependency list short, the container
small and the tests hermetic.

Entity expansion is disabled: a feed is untrusted input from the open web, and
an XML parser that resolves external entities is a file-disclosure bug waiting
to be reported.
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from mcpnews.ingest.extract import strip_html, summarise
from mcpnews.ingest.fetcher import Fetcher
from mcpnews.sources.adapters._dates import parse_date
from mcpnews.sources.base import CandidateItem, FetchResult, SourceAdapter, register
from mcpnews.store.base import SourceRecord, SourceState

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rss": "http://purl.org/rss/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
}
_DECL = re.compile(r"^\s*<\?xml[^>]*\?>")
#: Including an internal subset, which is where entity declarations hide and
#: which contains ">" characters that a naive pattern stops at.
_DOCTYPE = re.compile(r"<!DOCTYPE[^>\[]*(?:\[.*?\])?\s*>", re.IGNORECASE | re.DOTALL)
#: Anything that is not one of the five XML built-ins or a numeric reference.
#: Publishers emit &nbsp; and &mdash; constantly; a strict parser dies on them,
#: and an entity we did not declare is exactly what an attacker would send.
_ENTITY = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#[0-9]+|#[xX][0-9a-fA-F]+);)[A-Za-z][\w.\-]*;")


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def _find(parent: ET.Element, *paths: str) -> ET.Element | None:
    for path in paths:
        found = parent.find(path, _NS)
        if found is not None:
            return found
    return None


def _parse_xml(text: str) -> ET.Element:
    # A DOCTYPE is the vector for entity-expansion attacks and carries nothing a
    # feed needs. Removing it is simpler and safer than configuring a parser.
    cleaned = _ENTITY.sub("", _DOCTYPE.sub("", text.lstrip("\ufeff \t\r\n")))
    return ET.fromstring(cleaned)


def _atom_link(entry: ET.Element) -> str:
    best = ""
    for link in entry.findall("atom:link", _NS) + entry.findall("link", _NS):
        rel = link.get("rel", "alternate")
        href = (link.get("href") or "").strip()
        if not href:
            continue
        if rel == "alternate":
            return href
        best = best or href
    return best


class _XmlFeedAdapter(SourceAdapter):
    async def fetch(self, source: SourceRecord, state: SourceState,
                    fetcher: Fetcher) -> FetchResult:
        r = await fetcher.get(source.url, etag=state.etag, last_modified=state.last_modified)
        if r.not_modified:
            return FetchResult(not_modified=True, etag=state.etag,
                               last_modified=state.last_modified)
        return FetchResult(
            items=self.parse(r.text, source),
            etag=r.headers.get("etag"),
            last_modified=r.headers.get("last-modified"),
        )

    def parse(self, text: str, source: SourceRecord) -> list[CandidateItem]:
        root = _parse_xml(text)
        tag = root.tag.split("}")[-1].lower()
        if tag == "feed":
            return self._parse_atom(root, source)
        if tag == "rdf":
            return self._parse_rss(root, source, rdf=True)
        return self._parse_rss(root, source)

    # ---- RSS 2.0 and RDF -------------------------------------------------
    def _parse_rss(self, root: ET.Element, source: SourceRecord,
                   *, rdf: bool = False) -> list[CandidateItem]:
        if rdf:
            entries = root.findall("rss:item", _NS) or root.findall(".//rss:item", _NS)
        else:
            channel = root.find("channel")
            entries = (channel.findall("item") if channel is not None
                       else root.findall(".//item"))
        out: list[CandidateItem] = []
        for e in entries:
            link = _text(_find(e, "link", "rss:link", "guid"))
            if not link and rdf:
                link = e.get(f"{{{_NS['rdf']}}}about", "")
            title = _text(_find(e, "title", "rss:title"))
            if not link or not title:
                continue
            raw_summary = _text(_find(e, "description", "rss:description", "dc:description"))
            full = _text(_find(e, "content:encoded"))
            published = parse_date(
                _text(_find(e, "pubDate", "dc:date", "rss:pubDate", "published")))
            out.append(CandidateItem(
                url=link,
                title=strip_html(title),
                published_at=published,
                lang=_text(_find(e, "dc:language")) or None,
                summary=summarise(strip_html(raw_summary)),
                body=strip_html(full) if full else "",
                guid=_text(_find(e, "guid", "dc:identifier")) or link,
                raw_meta={"source_name": source.name, "topics": source.topics,
                          "region": source.region,
                          "author": _text(_find(e, "author", "dc:creator"))},
            ))
        return out

    # ---- Atom 1.0 --------------------------------------------------------
    def _parse_atom(self, root: ET.Element, source: SourceRecord) -> list[CandidateItem]:
        out: list[CandidateItem] = []
        for e in root.findall("atom:entry", _NS) or root.findall("entry"):
            link = _atom_link(e)
            title = _text(_find(e, "atom:title", "title"))
            if not link or not title:
                continue
            summary = _text(_find(e, "atom:summary", "summary"))
            content = _text(_find(e, "atom:content", "content"))
            published = parse_date(_text(_find(e, "atom:published", "published"))) or \
                parse_date(_text(_find(e, "atom:updated", "updated")))
            author = _find(e, "atom:author/atom:name", "author/name")
            out.append(CandidateItem(
                url=link,
                title=strip_html(title),
                published_at=published,
                lang=e.get("{http://www.w3.org/XML/1998/namespace}lang"),
                summary=summarise(strip_html(summary or content)),
                body=strip_html(content) if content and len(content) > len(summary) else "",
                guid=_text(_find(e, "atom:id", "id")) or link,
                raw_meta={"source_name": source.name, "topics": source.topics,
                          "region": source.region, "author": _text(author)},
            ))
        return out


@register("rss")
class RssAdapter(_XmlFeedAdapter):
    """RSS 2.0 and RDF. Also parses Atom, because publishers mislabel constantly."""
    label_key = "sources.kind.rss"


@register("atom")
class AtomAdapter(_XmlFeedAdapter):
    label_key = "sources.kind.atom"


@register("arxiv")
class ArxivAdapter(_XmlFeedAdapter):
    """arXiv's API returns Atom; the only difference is building the query.

    ``min_delay_s`` in the source config is respected by the fetcher's per-host
    spacing, which is where politeness belongs.
    """
    label_key = "sources.kind.atom"

    async def fetch(self, source: SourceRecord, state: SourceState,
                    fetcher: Fetcher) -> FetchResult:
        cfg = source.config or {}
        categories = cfg.get("categories") or ["cs.AI"]
        query = "+OR+".join(f"cat:{c}" for c in categories)
        url = (f"{source.url}?search_query={query}"
               f"&sortBy=submittedDate&sortOrder=descending"
               f"&max_results={int(cfg.get('max_results', 100))}")
        r = await fetcher.get(url)
        return FetchResult(items=self.parse(r.text, source))


@register("sitemap")
class SitemapAdapter(_XmlFeedAdapter):
    """Google News sitemaps. A urlset of <url> rather than <item> or <entry>."""
    label_key = "sources.kind.rss"

    def parse(self, text: str, source: SourceRecord) -> list[CandidateItem]:
        root = _parse_xml(text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
              "news": "http://www.google.com/schemas/sitemap-news/0.9"}
        out: list[CandidateItem] = []
        for u in root.findall("sm:url", ns) or root.findall("url"):
            loc = _text(u.find("sm:loc", ns) if u.find("sm:loc", ns) is not None
                        else u.find("loc"))
            if not loc:
                continue
            title_node = u.find("news:news/news:title", ns)
            date_node = u.find("news:news/news:publication_date", ns)
            lastmod = u.find("sm:lastmod", ns) if u.find("sm:lastmod", ns) is not None \
                else u.find("lastmod")
            out.append(CandidateItem(
                url=loc,
                title=_text(title_node) or loc,
                published_at=parse_date(_text(date_node) or _text(lastmod)),
                guid=loc,
                raw_meta={"source_name": source.name, "topics": source.topics,
                          "region": source.region},
            ))
        return out
