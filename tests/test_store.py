"""The SQLite backend, exercised through the interface every other backend must meet."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mcpnews.store.base import ArticleRecord, SourceRecord, SourceState


def _iso(delta_hours: float = 0) -> str:
    return (datetime.now(UTC) - timedelta(hours=delta_hours)).isoformat(
        timespec="seconds")


def _article(url: str, title: str, score: float = 5.0, hours: float = 1,
             simhash: int = 0) -> ArticleRecord:
    return ArticleRecord(
        url=url, original_url=url, domain="example.com", title=title,
        body=f"{title} body text", summary=title, published_at=_iso(hours),
        fetched_at=_iso(hours), interest_score=score, simhash=simhash,
        matched_rules=[{"name": "Test", "points": score, "section": "interests"}])


def test_insert_and_read_back(store):
    article_id = store.insert_article(_article("https://example.com/a", "Alpha"))
    got = store.get_article(article_id)
    assert got.title == "Alpha"
    assert got.cluster_id == article_id          # its own cluster until proven otherwise
    assert store.find_by_url("https://example.com/a") == article_id
    assert store.find_by_url("https://example.com/nope") is None


def test_feed_applies_decay_as_a_view_without_changing_the_store(store):
    fresh = store.insert_article(_article("https://example.com/fresh", "Fresh", 5.0, hours=1))
    old = store.insert_article(_article("https://example.com/old", "Old", 6.0, hours=200))

    by_interest = store.feed(hours=1000, limit=10, min_score=0, half_life_h=0)
    assert [a.id for a in by_interest][:2] == [old, fresh]

    by_freshness = store.feed(hours=1000, limit=10, min_score=0, half_life_h=36)
    assert by_freshness[0].id == fresh

    # The stored score is untouched by either view.
    assert store.get_article(old).interest_score == 6.0


def test_min_score_threshold_hides_but_does_not_delete(store):
    store.insert_article(_article("https://example.com/low", "Low", 0.2))
    assert store.feed(hours=100, limit=10, min_score=1.0, half_life_h=0) == []
    assert store.counts()["articles"] == 1
    assert store.keyword_search("Low")


def test_keyword_search_and_snippets(store):
    store.insert_article(_article("https://example.com/s", "Lithography exports tighten"))
    hits = store.keyword_search("lithography")
    assert hits and hits[0][0].title.startswith("Lithography")
    # Free text with FTS operators in it must not raise.
    assert store.keyword_search('AND OR "unbalanced') == []


def test_near_duplicate_clustering(store):
    from mcpnews.ingest.simhash import simhash

    # Wire copy: the same agency story, lightly re-headlined by a second outlet.
    text = ("Export control rules tighten on lithography tools sold into several markets. "
            "Officials said the measures take effect next quarter and cover both new and "
            "refurbished equipment, with a licence required for each shipment. Industry "
            "groups warned the paperwork burden would fall hardest on smaller suppliers.")
    variant = "Lithography curbs widen. " + text.replace("Officials said", "Officials stated")
    first = store.insert_article(_article("https://example.com/1", "A", simhash=simhash(text)))
    cluster = store.near_duplicate(simhash(variant))
    assert cluster == first
    assert store.near_duplicate(simhash(
        "Municipal recycling collection schedules change next month across the county, with "
        "new bins issued to households and a revised calendar published online.")) is None


def test_feed_shows_one_article_per_cluster(store):
    from mcpnews.ingest.simhash import simhash

    text = "Export control rules tighten on lithography tools."
    first = store.insert_article(_article("https://example.com/1", "A", simhash=simhash(text)))
    dup = _article("https://example.com/2", "B", simhash=simhash(text + " again"))
    dup.cluster_id = first
    store.insert_article(dup)
    ids = [a.id for a in store.feed(hours=100, limit=10, min_score=0, half_life_h=0)]
    assert ids == [first]


def test_source_status_is_owned_by_the_database(store):
    record = SourceRecord(id="s1", name="S", kind="rss", url="https://example.org/f")
    assert store.upsert_source(record) is True
    store.set_source_status("s1", "paused")
    record.name = "S renamed"
    record.status = "active"                     # as the file would still say
    assert store.upsert_source(record) is False
    stored = store.get_source("s1")
    assert stored.status == "paused" and stored.name == "S renamed"


def test_due_sources_respects_the_politeness_window(store):
    store.upsert_source(SourceRecord(id="s1", name="S", kind="rss", url="https://e.org/f"))
    assert [s.id for s in store.due_sources(_iso())] == ["s1"]

    state = store.get_source_state("s1")
    state.next_allowed_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    store.save_source_state(state)
    assert store.due_sources(_iso()) == []


def test_paused_sources_are_not_polled(store):
    store.upsert_source(SourceRecord(id="s1", name="S", kind="rss", url="https://e.org/f"))
    store.set_source_status("s1", "paused")
    assert store.due_sources(_iso()) == []


def test_vectors_never_mix_two_model_spaces(store):
    a = store.insert_article(_article("https://example.com/v1", "One"))
    b = store.insert_article(_article("https://example.com/v2", "Two"))
    store.save_vector(a, "model-a@3", [1.0, 0.0, 0.0])
    store.save_vector(b, "model-b@3", [1.0, 0.0, 0.0])

    hits = store.vector_search([1.0, 0.0, 0.0], "model-a@3", days=None)
    assert [h[0].id for h in hits] == [a]
    assert dict(store.vector_spaces()) == {"model-a@3": 1, "model-b@3": 1}


def test_pending_embedding_is_in_relevance_order(store):
    low = store.insert_article(_article("https://example.com/low", "Low", 1.0))
    high = store.insert_article(_article("https://example.com/high", "High", 9.0))
    assert [a.id for a in store.pending_embedding()] == [high, low]
    store.set_enrichment(high, "embedded", "done")
    assert [a.id for a in store.pending_embedding()] == [low]
    assert store.counts()["enriched"] == 1


def test_meta_round_trip(store):
    assert store.get_meta("nothing") is None
    store.set_meta("last_collection", "2026-09-01T00:00:00+00:00")
    assert store.get_meta("last_collection").startswith("2026-09-01")


def test_source_state_round_trip(store):
    store.upsert_source(SourceRecord(id="s1", name="S", kind="rss", url="https://e.org/f"))
    state = SourceState(source_id="s1", etag='W/"abc"', consecutive_failures=2,
                        last_error="boom")
    store.save_source_state(state)
    got = store.get_source_state("s1")
    assert got.etag == 'W/"abc"' and got.consecutive_failures == 2
