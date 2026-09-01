"""Local filesystem archive. The default, and the one that actually works.

Handles the case the project cares about most: a folder chosen by the reader,
which may be a bind-mounted host directory on any operating system. Nothing here
assumes POSIX semantics beyond what pathlib already normalises.
"""
from __future__ import annotations

import contextlib
import gzip
import json
import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path

from mcpnews.storage.base import BlobStorage, StorageError, Usage, normalise_key, register

#: Blobs above this compress well and are worth the CPU; below it, not.
_GZIP_MIN_BYTES = 512


@register("local")
class LocalStorage(BlobStorage):
    kind = "local"

    def __init__(self, root: str | Path, **_options):
        self.root = Path(root).expanduser()

    # ---- helpers ---------------------------------------------------------
    def _path(self, key: str) -> Path:
        safe = normalise_key(key)
        return self.root.joinpath(*safe.split("/"))

    # ---- interface -------------------------------------------------------
    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream",
            metadata: dict[str, str] | None = None) -> str:
        path = self._path(key)
        gz = len(data) >= _GZIP_MIN_BYTES
        if gz:
            path = path.with_name(path.name + ".gz")
            payload = gzip.compress(data, compresslevel=6)
        else:
            payload = data
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
            os.replace(tmp, path)
            if metadata:
                path.with_name(path.name + ".meta.json").write_text(
                    json.dumps({**metadata, "content_type": content_type}), encoding="utf-8")
        except OSError as exc:
            raise StorageError("err.path.not_writable", str(exc)) from exc
        return normalise_key(key) + (".gz" if gz else "")

    def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            if path.suffix == ".gz":
                return gzip.decompress(path.read_bytes())
            if path.is_file():
                return path.read_bytes()
            gzpath = path.with_name(path.name + ".gz")
            if gzpath.is_file():
                return gzip.decompress(gzpath.read_bytes())
        except OSError as exc:
            raise StorageError("err.generic", str(exc)) from exc
        raise StorageError("err.not_found", key)

    def exists(self, key: str) -> bool:
        path = self._path(key)
        return path.is_file() or path.with_name(path.name + ".gz").is_file()

    def delete(self, key: str) -> None:
        for candidate in (self._path(key), self._path(key + ".gz")):
            candidate.unlink(missing_ok=True)

    def list(self, prefix: str = "") -> Iterable[str]:
        base = self.root if not prefix else self._path(prefix)
        if not base.is_dir():
            return []
        out = []
        for p in base.rglob("*"):
            if p.is_file() and not p.name.endswith(".meta.json"):
                out.append(p.relative_to(self.root).as_posix())
        return sorted(out)

    def usage(self) -> Usage:
        blobs = 0
        total = 0
        if self.root.is_dir():
            for p in self.root.rglob("*"):
                if p.is_file():
                    blobs += 1
                    with contextlib.suppress(OSError):
                        total += p.stat().st_size
        return Usage(blobs=blobs, bytes=total)

    def describe(self) -> dict:
        free = None
        with contextlib.suppress(OSError):
            free = shutil.disk_usage(self.root).free
        return {"kind": self.kind, "location": str(self.root), "free_bytes": free}

    def health(self) -> tuple[bool, str]:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False, "err.path.cannot_create"
        probe = self.root / ".mcpnews-write-probe"
        try:
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError:
            return False, "err.path.not_writable"
        return True, ""
