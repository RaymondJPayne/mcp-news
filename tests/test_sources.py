"""Adapters, sniffing and the dated source lifecycle. Fixture in, candidates out."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcpnews.sources.registry import adapter_for, sniff_kind
from mcpnews.store.base import SourceRecord

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SOURCE = SourceRecord(id="probe", name="Example", kind="rss", url="https://example.org/feed",
                      topics=["test"], region="global")


def test_rss_adapter_parses_a_fixture():
    items = adapter_for("rss").parse((FIXTURES / "sample_rss.xml").read_text(), SOURCE)
    assert len(items) == 2
    first = items[0]
    assert first.title == "Export control rules tighten on lithography tools"
    assert first.published_at.startswith("2026-09-01T08:15")
    assert "lithography" in first.body
    assert first.raw_meta["author"] == "A Reporter"


def test_atom_adapter_parses_a_fixture():
    items = adapter_for("atom").parse((FIXTURES / "sample_atom.xml").read_text(), SOURCE)
    assert len(items) == 1
    assert items[0].url == "https://example.net/papers/1"
    assert items[0].published_at.startswith("2026-09-01T06:00")


def test_json_feed_adapter_parses_a_fixture():
    items = adapter_for("json_feed").parse(
        (FIXTURES / "sample_jsonfeed.json").read_text(), SOURCE)
    assert len(items) == 2
    assert items[0].title == "Lithography supply chain under pressure"


def test_json_feed_adapter_handles_a_mapped_plain_api():
    source = SourceRecord(
        id="p", name="P", kind="json_feed", url="https://example.org",
        config={"items_path": "vulnerabilities",
                "map": {"title": "vulnerabilityName", "published": "dateAdded", "id": "cveID"},
                "url_template": "https://example.org/cve/{id}"})
    payload = json.dumps({"vulnerabilities": [
        {"cveID": "CVE-2026-1", "vulnerabilityName": "Thing", "dateAdded": "2026-09-01"}]})
    items = adapter_for("json_feed").parse(payload, source)
    assert items[0].url == "https://example.org/cve/CVE-2026-1"
    assert items[0].title == "Thing"


def test_geojson_shape_is_understood():
    payload = json.dumps({"features": [
        {"properties": {"title": "M 5.0 somewhere", "url": "https://example.org/q/1",
                        "time": 1756704000000}}]})
    items = adapter_for("json_feed").parse(payload, SOURCE)
    assert items and items[0].title == "M 5.0 somewhere"


def test_xml_doctype_is_not_expanded():
    """A feed is untrusted input; an XML parser that resolves entities is a bug."""
    hostile = ('<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
               '<rss version="2.0"><channel><item><title>&x;</title>'
               '<link>https://example.org/a</link></item></channel></rss>')
    items = adapter_for("rss").parse(hostile, SOURCE)
    assert not any("root:" in (i.title or "") for i in items)


@pytest.mark.parametrize("text,expected", [
    ('{"items": []}', "json_feed"),
    ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>', "atom"),
    ('<?xml version="1.0"?><rss version="2.0"><channel/></rss>', "rss"),
    ("<html><body>not a feed</body></html>", None),
])
def test_sniffing(text, expected):
    assert sniff_kind(text) == expected


def test_bundles_validate_and_load(sandbox):
    from mcpnews.sources import loader

    bundles = loader.load_bundles(skip_broken=False)
    names = {b.name for b in bundles}
    assert {"core-world", "gov-agency", "tech-science"} <= names
    assert loader.bundle_errors() == []
    for bundle in bundles:
        for source in bundle.sources:
            assert source.added and source.verified and source.expires


def test_loader_never_overwrites_a_status_the_reader_changed(sandbox, store):
    """A restart must not resurrect a source the reader switched off."""
    from mcpnews.sources import loader

    loader.register_bundles(store, ["core-world"])
    first = store.list_sources()[0]
    store.set_source_status(first.id, "paused")

    loader.register_bundles(store, ["core-world"])          # as a restart would
    assert store.get_source(first.id).status == "paused"


def test_status_toggle_is_mirrored_into_the_file(sandbox, store):
    from mcpnews.sources import loader

    loader.register_bundles(store, ["core-world"])
    source_id = store.list_sources()[0].id
    assert loader.write_status_back(source_id, "paused")
    reloaded = [s for b in loader.load_bundles() for s in b.sources if s.id == source_id]
    assert reloaded and reloaded[0].status == "paused"


def test_expired_sources_are_flagged_not_disabled(sandbox, store):
    from mcpnews.sources import loader

    loader.register_bundles(store, ["core-world"])
    record = store.list_sources()[0]
    record.expires = "2000-01-01"
    store.upsert_source(record)
    report = loader.check(store)
    assert report["expired"] >= 1
    assert store.get_source(record.id).status == "active"
