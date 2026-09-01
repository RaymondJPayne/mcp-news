"""Filesystem locations, resolved the same way on Windows, macOS, Linux and in Docker.

No host-OS-specific path literals leak out of this module. Everything else in the
codebase asks here.

Resolution order for every directory:

1. The explicit environment variable, if set.
2. The repository checkout, when the package is being run from a source tree.
3. A per-user application directory appropriate to the platform.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIRNAME = "mcp-news"


def _from_env(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else None


def _repo_root() -> Path | None:
    """The checkout root when running from source, else None.

    ``src/mcpnews/paths.py`` -> parents[2] is the repository root. An installed
    wheel has no ``pyproject.toml`` beside it, so this returns None there.
    """
    here = Path(__file__).resolve()
    if len(here.parents) < 3:
        return None
    root = here.parents[2]
    return root if (root / "pyproject.toml").exists() else None


def _user_base(kind: str) -> Path:
    """Per-user config/data directory for the current platform."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / APP_DIRNAME / kind
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIRNAME / kind
    if kind == "config":
        xdg = os.environ.get("XDG_CONFIG_HOME")
        return (Path(xdg) if xdg else Path.home() / ".config") / APP_DIRNAME
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / APP_DIRNAME


def config_dir() -> Path:
    p = _from_env("MCPNEWS_CONFIG_DIR")
    if p is None:
        root = _repo_root()
        p = (root / "config") if root else _user_base("config")
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    p = _from_env("MCPNEWS_DATA_DIR")
    if p is None:
        root = _repo_root()
        p = (root / "data") if root else _user_base("data")
    p.mkdir(parents=True, exist_ok=True)
    return p


def archive_dir() -> Path:
    p = _from_env("MCPNEWS_ARCHIVE_DIR")
    if p is None:
        p = data_dir() / "archive"
    p.mkdir(parents=True, exist_ok=True)
    return p


def web_dir() -> Path:
    """Static dashboard files. Never created — if it is missing, that is a bug."""
    p = _from_env("MCPNEWS_WEB_DIR")
    if p is not None:
        return p
    root = _repo_root()
    if root and (root / "web").is_dir():
        return root / "web"
    # Installed layout: the Dockerfile copies web/ next to the app root.
    for candidate in (Path("/app/web"), Path.cwd() / "web"):
        if candidate.is_dir():
            return candidate
    return Path("/app/web")


def sources_dir() -> Path:
    p = config_dir() / "sources"
    p.mkdir(parents=True, exist_ok=True)
    return p


def is_writable(path: Path) -> tuple[bool, str]:
    """Can we actually create files here? Returns (ok, reason_key).

    Used by the setup wizard so a non-technical reader is told plainly that the
    folder they picked cannot be written to, rather than meeting a traceback
    three screens later.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False, "err.path.cannot_create"
    probe = path / ".mcpnews-write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False, "err.path.not_writable"
    return True, ""
