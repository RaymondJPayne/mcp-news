"""The string catalogue.

Every user-visible string in the dashboard, the setup wizard and the API lives in
``web/i18n/<lang>.json``. Nothing in this package, in the templates or in the
JavaScript hardcodes a human-readable sentence.

The format is deliberately the dullest thing that works: a flat JSON object,
dot-path keys, ``{named}`` placeholders, no nesting, no plural machinery, no
compile step. Adding a language is copying one file and translating the values.
See ``docs/LOCALIZATION.md``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from mcpnews.paths import web_dir

DEFAULT_LANG = "en"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def i18n_dir() -> Path:
    return web_dir() / "i18n"


@lru_cache(maxsize=1)
def meta() -> dict:
    path = i18n_dir() / "_meta.json"
    if not path.is_file():
        return {"locales": {DEFAULT_LANG: {"name": "English", "endonym": "English", "dir": "ltr"}}}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=32)
def _raw(lang: str) -> dict[str, str]:
    path = i18n_dir() / f"{lang}.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if isinstance(v, str)}


def available_locales() -> list[dict]:
    """Every locale with a catalogue file, in the order _meta.json declares them.

    A file present but undeclared still appears — a translator who forgot to edit
    _meta.json should not have their work silently ignored.
    """
    declared = meta().get("locales", {})
    on_disk = {p.stem for p in i18n_dir().glob("*.json") if not p.stem.startswith("_")}
    out: list[dict] = []
    for code in list(declared) + sorted(on_disk - set(declared)):
        if code not in on_disk:
            continue
        info = declared.get(code, {})
        out.append({
            "code": code,
            "name": info.get("name", code),
            "endonym": info.get("endonym", info.get("name", code)),
            "dir": info.get("dir", "ltr"),
        })
    return out


def direction(lang: str) -> str:
    for loc in available_locales():
        if loc["code"] == lang:
            return loc["dir"]
    return "ltr"


def resolve(lang: str | None) -> str:
    """Pick the best supported locale for a requested one.

    ``pt-BR`` resolves to ``pt``; anything unknown resolves to English rather
    than to an empty screen.
    """
    if not lang:
        return DEFAULT_LANG
    codes = {loc["code"] for loc in available_locales()}
    lang = lang.strip().replace("_", "-")
    if lang in codes:
        return lang
    base = lang.split("-")[0].lower()
    if base in codes:
        return base
    for code in codes:
        if code.split("-")[0].lower() == base:
            return code
    return DEFAULT_LANG


def catalogue(lang: str) -> dict[str, str]:
    """The merged catalogue for a locale: English underneath, the locale on top.

    A missing key therefore degrades to English instead of rendering a raw
    dot-path at the reader. The parity test still fails on a missing key, because
    a partial catalogue is a bug even when it does not look like one.
    """
    lang = resolve(lang)
    merged = dict(_raw(DEFAULT_LANG))
    if lang != DEFAULT_LANG:
        merged.update(_raw(lang))
    return merged


@dataclass(frozen=True)
class Translator:
    lang: str
    strings: dict[str, str]

    def __call__(self, key: str, **params: object) -> str:
        return self.t(key, **params)

    def t(self, key: str, **params: object) -> str:
        template = self.strings.get(key)
        if template is None:
            # Showing the key is more useful to whoever must fix it than an
            # empty string, and it is obvious on screen.
            return key
        if not params:
            return template

        def sub(m: re.Match[str]) -> str:
            name = m.group(1)
            return str(params[name]) if name in params else m.group(0)

        return _PLACEHOLDER.sub(sub, template)


def translator(lang: str | None) -> Translator:
    code = resolve(lang)
    return Translator(code, catalogue(code))


def reload_catalogues() -> None:
    """Drop caches. Used by tests and by the settings screen after a language change."""
    _raw.cache_clear()
    meta.cache_clear()
