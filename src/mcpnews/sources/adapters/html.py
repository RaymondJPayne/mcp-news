"""CSS-selector extraction for feedless sites — declared, not implemented.

Registered so that ``kind: html`` in a source file fails at load with a clear
message naming the adapter, rather than a stack trace on the first poll.

What it would need: a selector for the item container, one for the link and one
for the title, plus an explicit opt-in per source, because scraping a page is
categorically different from reading a feed the publisher offers. The shipped
bundles will never contain one — docs/SOURCES.md §5 rules out scraped homepages.
"""
from __future__ import annotations

from mcpnews.ingest.fetcher import Fetcher
from mcpnews.sources.base import CandidateItem, FetchResult, SourceAdapter, register
from mcpnews.store.base import SourceRecord, SourceState

_MESSAGE = ("The html source adapter is not implemented in this release. "
            "Use rss, atom or json_feed.")


@register("html")
class HtmlAdapter(SourceAdapter):
    label_key = "sources.kind.rss"

    async def fetch(self, source: SourceRecord, state: SourceState,
                    fetcher: Fetcher) -> FetchResult:
        raise NotImplementedError(_MESSAGE)

    def parse(self, text: str, source: SourceRecord) -> list[CandidateItem]:
        raise NotImplementedError(_MESSAGE)
