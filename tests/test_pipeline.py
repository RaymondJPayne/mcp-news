"""The collection pipeline, against a feed served from a local socket.

No outbound network: an ephemeral HTTP server on 127.0.0.1 serves the fixtures.
That keeps the test honest about the whole path — fetch, extract, archive,
dedupe, score, store — without depending on anyone else's uptime.
"""
from __future__ import annotations

import asyncio
import http.server
import threading
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"

def _page(subject: str) -> str:
    paragraph = (f"The {subject} regime now covers lithography tooling sold into "
                 "several markets, and Brazil is named explicitly. ") * 4
    return (f"<html lang='en'><head><title>{subject}</title></head><body><nav>Menu</nav>"
            f"<article><p>{paragraph}</p></article><footer>Legal</footer></body></html>")


#: The feed points at this same server, so the whole path — feed, article page,
#: extraction, archive — is exercised without a single outbound request.
FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel><title>Example Wire</title><link>{base}/</link>
    <item>
      <title>Export control rules tighten on lithography tools</title>
      <link>{base}/news/export-control?utm_source=rss&amp;utm_medium=feed</link>
      <pubDate>Mon, 01 Sep 2026 08:15:00 +0000</pubDate>
      <description>New rules cover lithography tooling exports.</description>
    </item>
    <item>
      <title>Weekly horoscope</title>
      <link>{base}/fun/horoscope/</link>
      <pubDate>Mon, 01 Sep 2026 07:00:00 +0000</pubDate>
      <description>Nothing here matters.</description>
    </item>
  </channel>
</rss>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        base = f"http://{self.headers.get('Host')}"
        if self.path.startswith("/feed"):
            body = FEED.format(base=base).encode()
            ctype = "application/rss+xml"
        elif self.path == "/robots.txt":
            body, ctype = b"User-agent: *\nAllow: /\n", "text/plain"
        elif self.path.startswith("/fun/horoscope"):
            body, ctype = _page("astrology").encode(), "text/html; charset=utf-8"
        else:
            body, ctype = _page("export control").encode(), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


@pytest.fixture()
def feed_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _collector(sandbox):
    from mcpnews.archive import Archive
    from mcpnews.config import profile as profile_cfg
    from mcpnews.config.settings import load as load_settings
    from mcpnews.ingest.pipeline import Collector
    from mcpnews.storage.registry import open_storage
    from mcpnews.store.registry import open_store

    profile = profile_cfg.from_dict({
        "interests": [{"name": "Semiconductor policy",
                       "match": ["export control", "lithography"], "weight": 5}],
        "places": [{"name": "Brazil", "match": ["Brazil"], "weight": 4}],
        "mute": {"keywords": ["horoscope"]},
    })
    settings = load_settings()
    settings.collection.per_host_delay_s = 0.0
    settings.collection.respect_robots = True   # the fixture server serves robots.txt
    store = open_store(settings)
    archive = Archive(open_storage(settings))
    return Collector(settings, store, archive, profile), store, archive


def test_end_to_end_collection(sandbox, feed_server):
    from mcpnews.store.base import SourceRecord

    collector, store, archive = _collector(sandbox)
    store.upsert_source(SourceRecord(
        id="fixture", name="Fixture wire", kind="rss", url=f"{feed_server}/feed",
        interval_min=1, topics=["test"]))

    report = asyncio.run(collector.run_once())
    assert report.sources_polled == 1 and report.sources_failed == 0
    assert report.new_articles >= 1

    articles = list(store.iter_articles())
    assert len(articles) == 2

    # Tracking parameters are gone and the URL is canonical.
    relevant = next(a for a in articles if "export-control" in a.url)
    assert "utm_source" not in relevant.url
    assert relevant.url == f"{feed_server}/news/export-control"

    # The article page was fetched and its readable text extracted.
    assert "Menu" not in relevant.body and "lithography tooling" in relevant.body

    # Scored with no model at all.
    assert relevant.interest_score > 0
    assert any(r["name"] == "Semiconductor policy" for r in relevant.matched_rules)

    # Archived before any relevance decision, and readable back.
    assert relevant.archive_ref
    assert "lithography" in archive.read(relevant.archive_ref)["body"]

    # The muted item is stored and searchable, just never shown.
    horoscope = next(a for a in articles if "horoscope" in a.url)
    assert horoscope.interest_score == 0
    feed = store.feed(hours=100000, limit=10, min_score=1.0, half_life_h=0)
    assert horoscope.id not in [a.id for a in feed]

    # A second pass adds nothing: the canonical URL is already known.
    state = store.get_source_state("fixture")
    state.next_allowed_at = None
    store.save_source_state(state)
    second = asyncio.run(collector.run_once())
    assert second.new_articles == 0


def test_a_broken_source_does_not_end_the_run(sandbox, feed_server):
    from mcpnews.store.base import SourceRecord

    collector, store, _ = _collector(sandbox)
    store.upsert_source(SourceRecord(id="dead", name="Dead", kind="rss",
                                     url="http://127.0.0.1:1/feed", interval_min=1))
    store.upsert_source(SourceRecord(id="alive", name="Alive", kind="rss",
                                     url=f"{feed_server}/feed", interval_min=1))
    report = asyncio.run(collector.run_once())
    assert report.sources_failed == 1 and report.sources_polled == 1
    assert report.new_articles >= 1

    state = store.get_source_state("dead")
    assert state.consecutive_failures == 1 and state.last_error
    assert state.next_allowed_at  # backs off rather than hammering


def test_rescore_after_a_profile_edit_does_not_refetch(sandbox, feed_server):
    from mcpnews.config import profile as profile_cfg
    from mcpnews.ingest.pipeline import rescore
    from mcpnews.store.base import SourceRecord

    collector, store, _ = _collector(sandbox)
    store.upsert_source(SourceRecord(id="fixture", name="F", kind="rss",
                                     url=f"{feed_server}/feed", interval_min=1))
    asyncio.run(collector.run_once())

    narrower = profile_cfg.from_dict({
        "interests": [{"name": "Recycling", "match": ["municipal recycling"], "weight": 5}]})
    changed = rescore(store, narrower)
    assert changed == 2
    assert all(a.interest_score == 0 for a in store.iter_articles())
