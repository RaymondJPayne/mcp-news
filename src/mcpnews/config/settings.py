"""Runtime settings: the file the setup wizard writes and the settings screen edits.

``config/settings.yaml`` is the record of every choice a reader made in the GUI.
It is plain YAML because the reader owns their configuration and should be able
to read, copy and back it up — but nobody is ever *required* to open it.

Precedence, deliberately: a value present in settings.yaml wins over the
environment. The environment supplies the *defaults the wizard offers*, which is
how Docker gets sensible starting paths without overriding a choice the reader
made afterwards.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mcpnews import paths
from mcpnews.config.yamlio import read_yaml, write_yaml

SETTINGS_FILENAME = "settings.yaml"

_HEADER = """\
# mcp-news settings
#
# Written by the setup wizard and by the Settings screen. You never need to edit
# this by hand — but it is yours, it is readable, and it is portable.
"""


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


@dataclass
class CollectionSettings:
    interval_min: int = 15
    concurrency: int = 8
    per_host_delay_s: float = 2.0
    respect_robots: bool = True
    fetch_fulltext: bool = True
    max_body_bytes: int = 2_000_000
    user_agent: str = "mcp-news/0.1 (+https://github.com/RaymondJPayne/mcp-news)"


@dataclass
class SharingSettings:
    """What travels with an article the reader shares.

    ``attribution_url`` is a plain editable field. The value below is only the
    default the Settings screen offers; nothing else in the codebase may assume
    it, because the owner has not settled on where the credit should point.

    ``attribution_text`` empty means "use the catalogue default", which is how the
    credit line comes out in the reader's own language instead of in English.
    """

    attribution: bool = True
    attribution_url: str = "https://github.com/RaymondJPayne/mcp-news"
    attribution_text: str = ""


@dataclass
class StoreSettings:
    backend: str = "sqlite"
    dsn: str = ""          # empty means "derive from data_dir"


@dataclass
class BlobSettings:
    backend: str = "local"
    root: str = ""         # empty means "derive from archive_dir"
    options: dict = field(default_factory=dict)


@dataclass
class Settings:
    version: int = 1
    configured: bool = False
    language: str = "en"
    data_dir: str = ""
    archive_dir: str = ""
    bundles: list[str] = field(default_factory=list)
    collection: CollectionSettings = field(default_factory=CollectionSettings)
    sharing: SharingSettings = field(default_factory=SharingSettings)
    store: StoreSettings = field(default_factory=StoreSettings)
    blob: BlobSettings = field(default_factory=BlobSettings)

    # ---- derived ---------------------------------------------------------
    @property
    def data_path(self) -> Path:
        return Path(self.data_dir) if self.data_dir else paths.data_dir()

    @property
    def archive_path(self) -> Path:
        return Path(self.archive_dir) if self.archive_dir else paths.archive_dir()

    @property
    def db_path(self) -> Path:
        if self.store.dsn:
            return Path(self.store.dsn)
        return self.data_path / "mcpnews.sqlite"

    @property
    def blob_root(self) -> Path:
        return Path(self.blob.root) if self.blob.root else self.archive_path

    def to_dict(self) -> dict:
        return asdict(self)


def settings_path() -> Path:
    return paths.config_dir() / SETTINGS_FILENAME


def defaults() -> Settings:
    """What the wizard offers before the reader has chosen anything."""
    s = Settings()
    s.language = os.environ.get("MCPNEWS_LANGUAGE", "").strip() or "en"
    s.data_dir = str(paths.data_dir())
    s.archive_dir = str(paths.archive_dir())
    s.collection.concurrency = _env_int("FETCH_CONCURRENCY", 8)
    return s


def load() -> Settings:
    raw = read_yaml(settings_path(), default=None)
    if not isinstance(raw, dict):
        return defaults()
    base = defaults()
    s = Settings(
        version=int(raw.get("version", 1)),
        configured=bool(raw.get("configured", False)),
        language=str(raw.get("language") or base.language),
        data_dir=str(raw.get("data_dir") or base.data_dir),
        archive_dir=str(raw.get("archive_dir") or base.archive_dir),
        bundles=list(raw.get("bundles") or []),
    )
    col = raw.get("collection") or {}
    s.collection = CollectionSettings(
        interval_min=int(col.get("interval_min", base.collection.interval_min)),
        concurrency=int(col.get("concurrency", base.collection.concurrency)),
        per_host_delay_s=float(col.get("per_host_delay_s", base.collection.per_host_delay_s)),
        respect_robots=bool(col.get("respect_robots", base.collection.respect_robots)),
        fetch_fulltext=bool(col.get("fetch_fulltext", base.collection.fetch_fulltext)),
        max_body_bytes=int(col.get("max_body_bytes", base.collection.max_body_bytes)),
        user_agent=str(col.get("user_agent") or base.collection.user_agent),
    )
    sh = raw.get("sharing")
    if isinstance(sh, dict):
        # `.get(key, default)` rather than `or`: a reader who turned attribution
        # off wrote `false`, and `or` would quietly turn it back on for them.
        s.sharing = SharingSettings(
            attribution=bool(sh.get("attribution", base.sharing.attribution)),
            attribution_url=str(sh.get("attribution_url",
                                       base.sharing.attribution_url) or ""),
            attribution_text=str(sh.get("attribution_text", "") or ""),
        )
    st = raw.get("store") or {}
    s.store = StoreSettings(backend=str(st.get("backend") or "sqlite"),
                            dsn=str(st.get("dsn") or ""))
    bl = raw.get("blob") or {}
    s.blob = BlobSettings(
        backend=str(bl.get("backend") or "local"),
        root=str(bl.get("root") or ""),
        options=dict(bl.get("options") or {}),
    )
    return s


def save(s: Settings) -> None:
    write_yaml(settings_path(), s.to_dict(), header=_HEADER)


def is_configured() -> bool:
    return load().configured
