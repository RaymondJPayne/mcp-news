"""A locale that silently loses a key ships a screen with a dot-path on it.

These tests fail on a missing key rather than letting the runtime fallback hide
it, and they check the two things a translator most easily gets wrong:
placeholders and stray HTML.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

I18N = Path(__file__).resolve().parents[1] / "web" / "i18n"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def catalogues() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(I18N.glob("*.json")) if not p.stem.startswith("_")}


def test_english_catalogue_exists_and_is_flat():
    en = catalogues()["en"]
    assert en, "en.json is empty"
    for key, value in en.items():
        assert isinstance(value, str), f"{key} is not a plain string"
        assert "." in key, f"{key} is not a dot-path"


def test_at_least_one_second_locale_ships():
    """A mechanism proved by one locale is a mechanism nobody has tested."""
    assert len(catalogues()) >= 2


@pytest.mark.parametrize("lang", [p.stem for p in sorted(I18N.glob("*.json"))
                                  if not p.stem.startswith("_")])
def test_locale_has_every_english_key(lang):
    en = catalogues()["en"]
    other = catalogues()[lang]
    missing = sorted(set(en) - set(other))
    extra = sorted(set(other) - set(en))
    assert not missing, f"{lang}.json is missing: {missing}"
    assert not extra, f"{lang}.json has keys English does not: {extra}"


@pytest.mark.parametrize("lang", [p.stem for p in sorted(I18N.glob("*.json"))
                                  if not p.stem.startswith("_")])
def test_placeholders_match_english(lang):
    en = catalogues()["en"]
    other = catalogues()[lang]
    for key, template in en.items():
        assert set(PLACEHOLDER.findall(template)) == set(PLACEHOLDER.findall(other[key])), (
            f"{lang}.json:{key} does not carry the same placeholders as English")


@pytest.mark.parametrize("lang", [p.stem for p in sorted(I18N.glob("*.json"))
                                  if not p.stem.startswith("_")])
def test_no_markup_in_values(lang):
    """Values are inserted as text. A tag in a value is a translator's mistake."""
    for key, value in catalogues()[lang].items():
        assert "<" not in value and ">" not in value, f"{lang}.json:{key} contains markup"


def test_meta_declares_every_locale():
    meta = json.loads((I18N / "_meta.json").read_text(encoding="utf-8"))
    declared = set(meta["locales"])
    on_disk = set(catalogues())
    assert on_disk <= declared, f"_meta.json does not declare: {sorted(on_disk - declared)}"
    for code, info in meta["locales"].items():
        assert info["dir"] in ("ltr", "rtl"), f"{code} has an invalid direction"


def test_translator_falls_back_to_english(sandbox):
    from mcpnews.i18n import reload_catalogues, translator

    reload_catalogues()
    pt = translator("pt")
    assert pt.t("nav.today") != "nav.today"
    assert pt.t("common.count_articles", count=3) == "3 artigos"
    # An unknown locale still produces readable English rather than a blank screen.
    assert translator("xx-YY").t("nav.today") == "Today"
