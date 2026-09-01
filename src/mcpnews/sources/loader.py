"""Loading source bundles from YAML, with the lifecycle docs/SOURCES.md describes.

The file holds *intent*: url, kind, dates, why something changed. The database
holds *fetch state*: cursors, ETags, failure counts — and, once a source is
registered, its status, because the reader can switch sources off in the
dashboard and a container restart must not undo that.

Toggling in the dashboard writes back to the file as well when the file is
writable, so the two stay in step and a reader who does read the file is not
misled. If the config directory is mounted read-only, the database still wins
and nothing breaks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mcpnews import paths
from mcpnews.config.envsub import substitute
from mcpnews.config.yamlio import read_yaml, write_yaml
from mcpnews.sources.registry import registered as registered_kinds
from mcpnews.store.base import ArticleStore, SourceRecord

LOCAL_BUNDLE = "local"
_ID_OK = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_RESERVED = {"_schema.json", "README.md"}

#: A new source is asked to be re-verified a year out, matching the shipped bundles.
DEFAULT_EXPIRY_DAYS = 365


def today() -> str:
    """Calendar date in UTC.

    Lifecycle dates are compared against UTC everywhere else, and a source that
    expires at midnight in one time zone should not expire a day early for a
    reader in another.
    """
    return datetime.now(UTC).date().isoformat()


class BundleError(ValueError):
    """A bundle file that cannot be used, named so the reader can find it."""


@dataclass
class Bundle:
    name: str
    path: Path
    description: str = ""
    maintainer: str = ""
    updated: str | None = None
    sources: list[SourceRecord] = None  # type: ignore[assignment]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "maintainer": self.maintainer,
            "updated": self.updated,
            "source_count": len(self.sources or []),
            "editable": self.name == LOCAL_BUNDLE,
        }


# --- validation -------------------------------------------------------------
def _schema() -> dict | None:
    path = paths.sources_dir() / "_schema.json"
    if not path.is_file():
        return None
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def validate(raw: dict, *, filename: str = "") -> None:
    """JSON Schema first, then the checks a schema cannot express."""
    schema = _schema()
    if schema is not None:
        try:
            import jsonschema
        except ImportError:                       # pragma: no cover
            jsonschema = None                     # type: ignore[assignment]
        if jsonschema is not None:
            try:
                jsonschema.validate(raw, schema)
            except jsonschema.ValidationError as exc:  # type: ignore[union-attr]
                where = "/".join(str(p) for p in exc.absolute_path)
                raise BundleError(f"{filename or 'bundle'}: {where}: {exc.message}") from None

    known = set(registered_kinds())
    seen: set[str] = set()
    for entry in raw.get("sources") or []:
        sid = entry.get("id", "")
        if not _ID_OK.match(sid or ""):
            raise BundleError(f"{filename}: invalid source id {sid!r}")
        if sid in seen:
            raise BundleError(f"{filename}: duplicate source id {sid!r}")
        seen.add(sid)
        kind = entry.get("kind")
        if kind not in known:
            raise BundleError(
                f"{filename}: source {sid!r} has unknown kind {kind!r}; "
                f"registered adapters: {sorted(known)}")


# --- reading ----------------------------------------------------------------
def _record(entry: dict, bundle: str) -> SourceRecord:
    entry = substitute(entry)          # ${VAR} in a keyed endpoint
    return SourceRecord(
        id=entry["id"], name=entry["name"], kind=entry["kind"], url=entry["url"],
        lang=entry.get("lang", "en"), region=entry.get("region", "global"),
        topics=list(entry.get("topics") or []),
        interval_min=int(entry.get("interval_min", 60)),
        status=entry.get("status", "active"), added=entry.get("added"),
        verified=entry.get("verified"), expires=entry.get("expires"),
        replaced_by=entry.get("replaced_by"), notes=entry.get("notes"),
        config=dict(entry.get("config") or {}), auth=dict(entry.get("auth") or {}),
        bundle=bundle)


def bundle_files() -> list[Path]:
    return sorted(p for p in paths.sources_dir().glob("*.yaml") if p.name not in _RESERVED)


def load_bundle(path: Path) -> Bundle:
    raw = read_yaml(path, default=None)
    if not isinstance(raw, dict):
        raise BundleError(f"{path.name}: not a mapping")
    validate(raw, filename=path.name)
    name = raw.get("bundle") or path.stem
    return Bundle(
        name=name, path=path, description=raw.get("description", "") or "",
        maintainer=raw.get("maintainer", "") or "",
        updated=str(raw.get("updated")) if raw.get("updated") else None,
        sources=[_record(e, name) for e in (raw.get("sources") or [])])


def load_bundles(*, skip_broken: bool = True) -> list[Bundle]:
    out: list[Bundle] = []
    for path in bundle_files():
        try:
            out.append(load_bundle(path))
        except BundleError:
            if not skip_broken:
                raise
    return out


def bundle_errors() -> list[str]:
    """Every bundle that failed to load, for the Status screen."""
    problems = []
    for path in bundle_files():
        try:
            load_bundle(path)
        except BundleError as exc:
            problems.append(str(exc))
    return problems


# --- registration -----------------------------------------------------------
def register_bundles(store: ArticleStore, enabled: list[str]) -> dict[str, int]:
    """Push the chosen bundles into the database.

    Never touches ``status`` on a source that already exists — see the docstring
    on ``ArticleStore.upsert_source``.
    """
    added = updated = 0
    wanted = set(enabled) | {LOCAL_BUNDLE}
    for bundle in load_bundles():
        if bundle.name not in wanted:
            continue
        for source in bundle.sources or []:
            if store.upsert_source(source):
                added += 1
            else:
                updated += 1
    return {"added": added, "updated": updated}


# --- writing back -----------------------------------------------------------
def _raw_bundle(path: Path) -> dict:
    raw = read_yaml(path, default=None)
    if not isinstance(raw, dict):
        raise BundleError(f"{path.name}: not a mapping")
    return raw


def local_path() -> Path:
    return paths.sources_dir() / f"{LOCAL_BUNDLE}.yaml"


def ensure_local_bundle() -> Path:
    path = local_path()
    if not path.is_file():
        write_yaml(path, {
            "version": 1,
            "bundle": LOCAL_BUNDLE,
            "description": "Sources you added yourself. Never overwritten by an update.",
            "maintainer": "you",
            "updated": today(),
            "sources": [],
        }, header="# Your own sources. Added from the dashboard; yours to read and edit.")
    return path


def _entry_from(record: SourceRecord) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": record.id, "name": record.name, "kind": record.kind, "url": record.url,
        "lang": record.lang, "region": record.region, "topics": record.topics or ["general"],
        "interval_min": record.interval_min, "status": record.status,
        "added": record.added or today(),
        "verified": record.verified or today(),
        "expires": record.expires or (
            datetime.now(UTC).date() + timedelta(days=DEFAULT_EXPIRY_DAYS)).isoformat(),
    }
    for key in ("replaced_by", "notes"):
        value = getattr(record, key)
        if value:
            entry[key] = value
    if record.config:
        entry["config"] = record.config
    if record.auth:
        entry["auth"] = record.auth
    return entry


def add_local_source(record: SourceRecord) -> None:
    path = ensure_local_bundle()
    raw = _raw_bundle(path)
    sources = raw.setdefault("sources", [])
    if any(s.get("id") == record.id for s in sources):
        raise BundleError("err.source.duplicate_id")
    record.bundle = LOCAL_BUNDLE
    sources.append(_entry_from(record))
    raw["updated"] = today()
    validate(raw, filename=path.name)
    write_yaml(path, raw)


def remove_local_source(source_id: str) -> bool:
    path = local_path()
    if not path.is_file():
        return False
    raw = _raw_bundle(path)
    before = len(raw.get("sources") or [])
    raw["sources"] = [s for s in raw.get("sources") or [] if s.get("id") != source_id]
    if len(raw["sources"]) == before:
        return False
    raw["updated"] = today()
    write_yaml(path, raw)
    return True


def write_status_back(source_id: str, status: str) -> bool:
    """Mirror a dashboard toggle into whichever bundle file declares the source.

    Best effort by design: a read-only config mount is a legitimate deployment,
    and the database remains authoritative either way.
    """
    for path in bundle_files():
        try:
            raw = _raw_bundle(path)
        except BundleError:
            continue
        for entry in raw.get("sources") or []:
            if entry.get("id") == source_id:
                if entry.get("status") == status:
                    return True
                entry["status"] = status
                try:
                    write_yaml(path, raw)
                except OSError:
                    return False
                return True
    return False


def update_local_source(source_id: str, changes: dict[str, Any]) -> bool:
    path = local_path()
    if not path.is_file():
        return False
    raw = _raw_bundle(path)
    for entry in raw.get("sources") or []:
        if entry.get("id") == source_id:
            entry.update({k: v for k, v in changes.items() if v is not None})
            raw["updated"] = today()
            validate(raw, filename=path.name)
            write_yaml(path, raw)
            return True
    return False


# --- lifecycle reporting ----------------------------------------------------
def check(store: ArticleStore) -> dict[str, Any]:
    """What ``mcpnews sources check`` and the Sources screen both report.

    An expired source is flagged, never disabled. The point is that a stale list
    becomes visible, which is exactly what a database table full of silently
    404-ing feeds never does.
    """
    now = datetime.now(UTC).date()
    ok = failing = expired = 0
    rows: list[dict] = []
    for source in store.list_sources():
        state = store.get_source_state(source.id)
        is_expired = bool(source.expires and str(source.expires) < now.isoformat())
        is_failing = state.consecutive_failures >= 3
        if source.status in ("active", "deprecated"):
            if is_failing:
                failing += 1
            else:
                ok += 1
        if is_expired:
            expired += 1
        rows.append({
            **source.to_dict(),
            "last_run_at": state.last_run_at,
            "last_ok_at": state.last_ok_at,
            "consecutive_failures": state.consecutive_failures,
            "last_error": state.last_error,
            "article_count": state.article_count,
            "expired": is_expired,
            "failing": is_failing,
        })
    return {"sources": rows, "ok": ok, "failing": failing, "expired": expired,
            "bundle_errors": bundle_errors()}
