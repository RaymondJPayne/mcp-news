"""YAML read and write, with the two properties config files actually need.

Files stay human-readable and portable because the reader owns them, even though
the dashboard is the primary editor. Writes are atomic so an interrupted save
never leaves a half-written profile behind.
"""
from __future__ import annotations

import datetime as _dt
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


def stringify_dates(value: Any) -> Any:
    """YAML parses ``2026-09-01`` into a date object; every consumer wants a string.

    Left unconverted it produces schema failures, JSON serialisation errors and
    date comparisons that silently do the wrong thing.
    """
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: stringify_dates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [stringify_dates(v) for v in value]
    return value


def read_yaml(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return default if data is None else stringify_dates(data)


def write_yaml(path: Path, data: Any, *, header: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    text = (header.rstrip() + "\n\n" if header else "") + body
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
