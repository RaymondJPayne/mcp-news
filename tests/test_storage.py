"""The blob archive: the local backend works, the remote ones say so plainly."""
from __future__ import annotations

import pytest

from mcpnews.storage.backends.local import LocalStorage
from mcpnews.storage.base import StorageError, normalise_key, registered
from mcpnews.storage.registry import describe_all


def test_keys_cannot_escape_the_root():
    assert normalise_key("/2026/09/a.json") == "2026/09/a.json"
    assert normalise_key("2026\\09\\a.json") == "2026/09/a.json"
    for bad in ("", "../../etc/passwd", "/../x"):
        with pytest.raises(StorageError):
            normalise_key(bad)


def test_local_storage_round_trip(tmp_path):
    store = LocalStorage(tmp_path / "archive")
    ok, key = store.health()
    assert ok and key == ""

    small = store.put("2026/09/small.json", b"tiny")
    assert store.get(small) == b"tiny"

    big = store.put("2026/09/big.json", b"x" * 5000)
    assert big.endswith(".gz")                       # compressed above the threshold
    assert store.get("2026/09/big.json") == b"x" * 5000
    assert store.exists("2026/09/big.json")

    assert sorted(store.list()) == sorted([small, big])
    assert store.usage().blobs == 2
    assert "location" in store.describe()

    store.delete("2026/09/big.json")
    assert not store.exists("2026/09/big.json")


def test_reading_something_that_is_not_there(tmp_path):
    with pytest.raises(StorageError):
        LocalStorage(tmp_path).get("nothing/here.json")


def test_remote_backends_are_registered_and_honest():
    assert {"local", "s3", "dropbox", "gdrive", "onedrive"} <= set(registered())
    described = {d["kind"]: d for d in describe_all()}
    assert described["local"]["implemented"] is True
    for kind in ("s3", "dropbox", "gdrive", "onedrive"):
        assert described[kind]["implemented"] is False
    assert described["dropbox"]["needs_oauth"] is True
    assert described["s3"]["needs_oauth"] is False


def test_an_unimplemented_backend_explains_itself():
    from mcpnews.storage.backends.remote import S3Storage

    with pytest.raises(NotImplementedError) as exc:
        S3Storage()
    assert "settings.yaml" in str(exc.value)


def test_archive_writes_before_any_relevance_decision(tmp_path):
    from mcpnews.archive import Archive, archive_key

    archive = Archive(LocalStorage(tmp_path))
    ref = archive.write(canonical_url="https://example.com/a", original_url="https://example.com/a",
                        title="T", body="B" * 100, published_at="2026-09-01T00:00:00+00:00")
    assert ref and archive.read(ref)["body"].startswith("B")
    assert archive_key("https://example.com/a", "2026-09-01T00:00:00+00:00").startswith("2026/09/")


def test_an_archive_failure_never_stops_collection(tmp_path):
    class Broken(LocalStorage):
        def put(self, *a, **kw):
            raise StorageError("err.path.not_writable")

    assert Archive_write(Broken(tmp_path)) is None


def Archive_write(storage):
    from mcpnews.archive import Archive

    return Archive(storage).write(canonical_url="https://x/y", original_url="https://x/y",
                                  title="t", body="b")


def test_store_backends_registered():
    from mcpnews.store.base import registered as store_registered
    from mcpnews.store.registry import registered as via_registry  # noqa: F401

    assert {"sqlite", "postgres", "mysql"} <= set(store_registered())


def test_unimplemented_store_backend_explains_itself():
    from mcpnews.store.backends.postgres import PostgresStore

    with pytest.raises(NotImplementedError) as exc:
        PostgresStore("postgresql://x")
    assert "sqlite" in str(exc.value)
