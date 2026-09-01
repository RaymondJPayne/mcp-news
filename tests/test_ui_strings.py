"""The dashboard must not contain a user-visible English literal.

This is the test that keeps internationalisation from rotting. It is crude on
purpose: a regex over the source files finds the mistake at the moment it is
made, which is the only time it is cheap to fix.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
EN = json.loads((WEB / "i18n" / "en.json").read_text(encoding="utf-8"))


def test_every_key_used_by_the_dashboard_exists():
    source = (WEB / "app.js").read_text(encoding="utf-8")
    used = set(re.findall(r"""\bt\(\s*["']([a-z0-9_.]+)["']""", source))
    used |= set(re.findall(r"""\btn\(\s*["']([a-z0-9_.]+)["']""", source))
    used |= set(re.findall(r'data-i18n="([a-z0-9_.]+)"',
                           (WEB / "index.html").read_text(encoding="utf-8")))
    # Keys built from a template literal are checked by prefix instead.
    dynamic_prefixes = ("tier.", "today.window.", "today.section.", "search.mode.",
                        "search.days.", "sources.status.", "profile.section.",
                        "setup.profile.starter.", "share.target.", "status.provider.")
    missing = sorted(k for k in used
                     if k not in EN and not k.startswith(dynamic_prefixes))
    assert not missing, f"app.js uses keys that en.json does not define: {missing}"


def test_dashboard_has_no_remote_asset_or_framework():
    for name in ("index.html", "app.js", "styles.css", "sw.js"):
        text = (WEB / name).read_text(encoding="utf-8")
        lowered = text.lower()
        for forbidden in ("http://cdn", "https://cdn", "unpkg.com", "jsdelivr",
                          "fonts.googleapis.com", "fonts.gstatic.com",
                          "googletagmanager", "google-analytics"):
            assert forbidden not in lowered, f"{name} references {forbidden}"


def test_stylesheet_uses_logical_properties_for_direction():
    """RTL has to be a dir attribute, not a second stylesheet."""
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    assert "inset-inline" in css and "border-inline-start" in css
    for physical in ("margin-left:", "margin-right:", "padding-left:", "padding-right:"):
        assert physical not in css.replace(" ", ""), f"{physical} is not direction-agnostic"
