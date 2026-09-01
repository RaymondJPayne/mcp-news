"""Sharing sends the publisher's link, or it sends nothing.

The tests that matter here are the ones that fail loudly if someone later makes
sharing "more helpful": share the local copy, keep the attribution on after the
reader turned it off, or truncate a URL to make room for a headline.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from mcpnews import share
from mcpnews.store.base import ArticleRecord

SOURCE = "https://example.org/world/2026/a-headline"
ENCODED = quote(SOURCE, safe="")
TITLE = "Export controls tighten again"
CREDIT = "Shared with mcp-news https://github.com/RaymondJPayne/mcp-news"


# ---------------------------------------------------------------- composition
def test_the_text_is_the_headline_then_the_link_then_the_credit():
    composed = share.compose(title=TITLE, url=SOURCE, attribution=CREDIT)
    assert composed["text"] == f"{TITLE}\n{SOURCE}\n{CREDIT}"
    # text_only exists for the platforms that take the link as its own field and
    # would otherwise show it twice.
    assert composed["text_only"] == f"{TITLE}\n{CREDIT}"
    assert SOURCE not in composed["text_only"]


def test_attribution_off_composes_without_it_and_leaves_nothing_behind():
    off = share.compose(title=TITLE, url=SOURCE, attribution="")
    assert off["text"] == f"{TITLE}\n{SOURCE}"
    assert off["attribution"] == ""
    assert "mcp-news" not in off["text"]
    assert "mcp-news" not in json.dumps(share.targets(url=SOURCE, title=TITLE))


def test_attribution_is_words_then_link_and_either_half_may_be_empty():
    assert share.attribution_line("Shared with mcp-news", "https://example.com") == (
        "Shared with mcp-news https://example.com")
    assert share.attribution_line("Shared with mcp-news", "") == "Shared with mcp-news"
    assert share.attribution_line("", "https://example.com") == "https://example.com"
    assert share.attribution_line("", "") == ""


def test_a_long_headline_is_truncated_and_the_urls_are_not():
    long_title = "Ministers agree a framework " * 20
    composed = share.compose(title=long_title, url=SOURCE, attribution=CREDIT)
    assert len(composed["text"]) <= share.MAX_LENGTH
    assert composed["text"].endswith(CREDIT)
    assert SOURCE in composed["text"]                    # whole, never shortened
    assert composed["title"].endswith(share.ELLIPSIS)
    assert composed["full_title"].startswith("Ministers agree")


def test_when_the_urls_alone_fill_the_budget_the_headline_goes_rather_than_a_link():
    huge = "https://example.org/" + ("segment/" * 40)
    composed = share.compose(title=TITLE, url=huge, attribution=CREDIT)
    assert huge in composed["text"] and CREDIT in composed["text"]
    assert composed["title"] == ""


# -------------------------------------------------------------- what is shared
@pytest.mark.parametrize("url", [
    "http://localhost:8378/#/article/12",
    "http://127.0.0.1:8378/api/article/12",
    "http://[::1]:8378/",
    "https://mcp-news.local/article/12",
    "http://192.168.1.20:8378/",
    "http://10.0.0.4/",
    "http://raspberrypi.localhost/",
    "file:///home/reader/archive/12.html",
    "/api/article/12",
    "javascript:alert(1)",
    "",
    "   ",
])
def test_a_local_or_unusable_address_is_never_shareable(url):
    assert share.is_shareable(url) is False
    assert share.payload(url=url, title=TITLE) is None
    assert share.targets(url=url, title=TITLE) is None


@pytest.mark.parametrize("url", [
    "https://example.org/a", "http://news.example.co.uk/x?y=1", "https://8.8.8.8/a",
])
def test_a_publisher_address_is_shareable(url):
    assert share.is_shareable(url) is True


# ------------------------------------------------------------ url construction
def _query(href: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(href).query, keep_blank_values=True)


def _by_id(instance: str = "") -> dict[str, str]:
    built = share.targets(url=SOURCE, title=TITLE, attribution=CREDIT, instance=instance)
    return {row["id"]: row["href"] for row in built}


def test_every_target_is_covered_and_ordered():
    assert share.TARGET_IDS == ("mastodon", "bluesky", "linkedin", "reddit", "whatsapp",
                                "telegram", "facebook", "x", "email")


@pytest.mark.parametrize("target", share.TARGETS, ids=lambda t: t.id)
def test_every_target_carries_the_source_link_and_nothing_else(target):
    href = _by_id("mastodon.social")[target.id]
    assert ENCODED in href, "the publisher's link has to reach the platform"
    assert "{" not in href and "}" not in href
    assert href.startswith(("https://", "mailto:"))


def test_each_target_builds_the_url_that_platform_documents():
    hrefs = _by_id("mastodon.social")
    text = quote(f"{TITLE}\n{SOURCE}\n{CREDIT}", safe="")
    text_only = quote(f"{TITLE}\n{CREDIT}", safe="")

    assert hrefs["mastodon"] == f"https://mastodon.social/share?text={text}"
    assert hrefs["bluesky"] == f"https://bsky.app/intent/compose?text={text}"
    assert hrefs["linkedin"] == (
        f"https://www.linkedin.com/sharing/share-offsite/?url={ENCODED}")
    assert hrefs["reddit"] == (
        f"https://www.reddit.com/submit?url={ENCODED}&title={quote(TITLE, safe='')}")
    assert hrefs["whatsapp"] == f"https://wa.me/?text={text}"
    assert hrefs["telegram"] == f"https://t.me/share/url?url={ENCODED}&text={text_only}"
    assert hrefs["facebook"] == (
        f"https://www.facebook.com/sharer/sharer.php?u={ENCODED}")
    assert hrefs["x"] == f"https://x.com/intent/post?url={ENCODED}&text={text_only}"
    assert hrefs["email"] == (
        f"mailto:?subject={quote(TITLE, safe='')}&body={text}")


def test_a_headline_full_of_punctuation_cannot_escape_its_parameter():
    hostile = "Rates & prices #up? yes=maybe/definitely"
    hrefs = {row["id"]: row["href"]
             for row in share.targets(url=SOURCE, title=hostile, attribution=CREDIT)}
    assert _query(hrefs["reddit"])["title"] == [hostile]
    assert _query(hrefs["reddit"])["url"] == [SOURCE]
    # One parameter each: nothing was smuggled in as a second one.
    assert list(_query(hrefs["x"])) == ["url", "text"]


def test_mastodon_keeps_a_placeholder_until_the_reader_names_their_server():
    assert _by_id()["mastodon"].startswith("https://{instance}/share?text=")


@pytest.mark.parametrize(("typed", "expected"), [
    ("mastodon.social", "mastodon.social"),
    ("  MASTODON.SOCIAL  ", "mastodon.social"),
    ("https://mastodon.social/@reader", "mastodon.social"),
    ("https://mastodon.social:443/", "mastodon.social"),
    ("@reader@mastodon.social", "mastodon.social"),
    ("not a server", ""),
    ("localhost", ""),
    ("", ""),
])
def test_a_mastodon_server_is_read_the_way_a_reader_types_it(typed, expected):
    assert share.normalise_instance(typed) == expected


def test_an_unusable_mastodon_server_leaves_the_placeholder_rather_than_a_broken_link():
    assert "{instance}" in _by_id("not a server")["mastodon"]


def test_the_link_only_platforms_say_so():
    carries = {row.id: row.carries_text for row in share.TARGETS}
    assert carries["linkedin"] is False and carries["facebook"] is False
    assert carries["reddit"] is False          # a title, but no room for the credit
    assert carries["mastodon"] is True and carries["email"] is True


# ------------------------------------------------------------------ the api
def _setup(client, sandbox):
    return client.post("/api/setup/complete", json={
        "language": "en",
        "data_dir": str(sandbox / "data"),
        "archive_dir": str(sandbox / "archive"),
        "bundles": ["core-world"],
        "interests": [{"name": "Exports", "match": ["export controls"], "weight": 5}],
    })


def _article(client, url: str = SOURCE, title: str = TITLE) -> int:
    now = datetime.now(UTC) - timedelta(hours=1)
    return client.app.state.app.store.insert_article(ArticleRecord(
        url=url, original_url=url, domain="example.org", title=title,
        summary="Something happened.", published_at=now.isoformat(),
        fetched_at=now.isoformat(), interest_score=6.0))


def test_the_feed_and_the_article_both_offer_the_publishers_link(client, sandbox):
    _setup(client, sandbox)
    article_id = _article(client)

    item = next(i for i in client.get("/api/foryou").json()["items"]
                if i["article_id"] == article_id)
    assert item["share"]["url"] == SOURCE
    assert item["share"]["title"] == TITLE

    detail = client.get(f"/api/article/{article_id}").json()
    assert detail["share"]["url"] == SOURCE


def test_the_share_endpoint_never_hands_out_the_local_copy(client, sandbox):
    _setup(client, sandbox)
    article_id = _article(client)
    body = client.get(f"/api/share/{article_id}").json()
    assert body["url"] == SOURCE

    blob = json.dumps(body)
    for local in ("testserver", "localhost", "127.0.0.1", "0.0.0.0",
                  f"article/{article_id}", "/api/"):
        assert local not in blob, f"the share payload leaked {local}"
    assert len(body["targets"]) == len(share.TARGETS)


def test_an_article_with_no_source_link_offers_no_share_at_all(client, sandbox):
    """The dashboard renders nothing when `share` is null. This is why."""
    _setup(client, sandbox)
    article_id = _article(client, url="", title="Orphan")

    item = next(i for i in client.get("/api/foryou").json()["items"]
                if i["article_id"] == article_id)
    assert item["share"] is None
    assert client.get(f"/api/article/{article_id}").json()["share"] is None

    refused = client.get(f"/api/share/{article_id}")
    assert refused.status_code == 400
    assert refused.json()["error"]["key"] == "err.share.unavailable"


def test_attribution_is_on_by_default_and_stays_off_once_turned_off(client, sandbox):
    _setup(client, sandbox)
    article_id = _article(client)

    on = client.get(f"/api/share/{article_id}").json()
    assert on["attribution"] == CREDIT
    assert on["text"].endswith(CREDIT)

    assert client.put("/api/settings", json={"sharing": {"attribution": False}}).status_code == 200
    off = client.get(f"/api/share/{article_id}").json()
    assert off["attribution"] == ""
    assert "mcp-news" not in json.dumps(off)

    # Saving something else must not quietly switch it back on.
    client.put("/api/settings", json={"collection": {"interval_min": 20}})
    assert client.get("/api/settings").json()["sharing"]["attribution"] is False
    assert client.get(f"/api/share/{article_id}").json()["attribution"] == ""


def test_the_attribution_line_is_a_plain_editable_field(client, sandbox):
    _setup(client, sandbox)
    article_id = _article(client)
    r = client.put("/api/settings", json={"sharing": {
        "attribution": True,
        "attribution_url": "https://raymondjpayne.example/news",
        "attribution_text": "Found with my own news reader",
    }})
    assert r.status_code == 200
    body = client.get(f"/api/share/{article_id}").json()
    assert body["attribution"] == (
        "Found with my own news reader https://raymondjpayne.example/news")
    assert "github.com" not in json.dumps(body)


def test_an_attribution_link_nobody_could_open_is_refused(client, sandbox):
    _setup(client, sandbox)
    r = client.put("/api/settings",
                   json={"sharing": {"attribution_url": "javascript:alert(1)"}})
    assert r.status_code == 400
    assert r.json()["error"]["key"] == "err.share.bad_url"


def test_the_credit_wording_defaults_to_the_readers_language(client, sandbox):
    _setup(client, sandbox)
    article_id = _article(client)
    client.put("/api/settings", json={"language": "pt"})
    body = client.get(f"/api/share/{article_id}").json()
    assert body["attribution"].startswith("Compartilhado com o mcp-news")


def test_the_readers_mastodon_server_reaches_the_link(client, sandbox):
    _setup(client, sandbox)
    article_id = _article(client)
    body = client.get(f"/api/share/{article_id}",
                      params={"instance": "https://ruby.social/@reader"}).json()
    mastodon = next(row for row in body["targets"] if row["id"] == "mastodon")
    assert mastodon["href"].startswith("https://ruby.social/share?text=")


# ------------------------------------------------------------------- catalogue
def test_every_target_and_message_has_a_name_in_every_locale():
    from pathlib import Path
    i18n = Path(__file__).resolve().parents[1] / "web" / "i18n"
    for path in sorted(i18n.glob("*.json")):
        if path.stem.startswith("_"):
            continue
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        for target_id in share.TARGET_IDS:
            assert f"share.target.{target_id}" in catalogue, f"{path.name}: {target_id}"
        assert share.ATTRIBUTION_TEXT_KEY in catalogue, path.name


def test_the_dashboard_can_copy_a_link_without_the_async_clipboard():
    """Plain HTTP on a home network has no navigator.clipboard. Both paths ship."""
    app_js = (__import__("pathlib").Path(__file__).resolve().parents[1]
              / "web" / "app.js").read_text(encoding="utf-8")
    assert 'document.execCommand("copy")' in app_js
    assert "navigator.clipboard" in app_js
    assert "setSelectionRange" in app_js       # iOS ignores select() on its own
