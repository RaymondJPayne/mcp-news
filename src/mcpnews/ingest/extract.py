"""Readable text extraction from an HTML page.

Uses ``trafilatura`` when it is installed, because it is better than anything
worth writing here, and falls back to a small built-in extractor when it is not.
The fallback is not a placeholder: it is what keeps the dependency optional, the
Docker image small, and the test suite free of a network and a heavy parser.
"""
from __future__ import annotations

import html
import re
import unicodedata

_SCRIPTISH = re.compile(
    r"<(script|style|noscript|template|svg|iframe|form|nav|aside|footer|header)\b.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCK_END = re.compile(
    r"</(p|div|section|article|h[1-6]|li|ul|ol|table|tr|blockquote|pre|br)\s*>|<br\s*/?>",
    re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t ]+")
_BLANKS = re.compile(r"\n{3,}")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_LANG = re.compile(r"<html[^>]*\blang\s*=\s*[\"']([A-Za-z-]{2,8})[\"']", re.IGNORECASE)
_ARTICLE = re.compile(r"<article\b.*?</article\s*>", re.IGNORECASE | re.DOTALL)

#: Below this a "body" is navigation furniture, not an article.
_MIN_BODY_CHARS = 200

try:  # pragma: no cover - exercised only where the optional dependency exists
    import trafilatura as _trafilatura
except Exception:  # noqa: BLE001
    _trafilatura = None


def strip_html(fragment: str) -> str:
    text = _COMMENT.sub(" ", fragment or "")
    text = _SCRIPTISH.sub(" ", text)
    text = _BLOCK_END.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFC", text)
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANKS.sub("\n\n", text).strip()


def _fallback_body(page: str) -> str:
    """Prefer an <article> element; fall back to the densest text on the page."""
    candidates = _ARTICLE.findall(page)
    best = ""
    for chunk in candidates:
        text = strip_html(chunk)
        if len(text) > len(best):
            best = text
    if len(best) >= _MIN_BODY_CHARS:
        return best
    whole = strip_html(page)
    # Drop the short lines that are almost always menus and cookie notices.
    lines = [line for line in whole.split("\n") if len(line) >= 40 or not line]
    joined = _BLANKS.sub("\n\n", "\n".join(lines)).strip()
    return joined if len(joined) >= _MIN_BODY_CHARS else whole


def extract(page_html: str, *, url: str | None = None) -> dict[str, str]:
    """Return ``{title, body, lang}``. Never raises: an empty body is a valid answer."""
    page_html = page_html or ""
    title = ""
    m = _TITLE.search(page_html)
    if m:
        title = html.unescape(strip_html(m.group(1))).strip()
    lang = ""
    m = _LANG.search(page_html)
    if m:
        lang = m.group(1).split("-")[0].lower()

    body = ""
    if _trafilatura is not None:  # pragma: no cover
        try:
            body = _trafilatura.extract(
                page_html, url=url, include_comments=False, include_tables=False,
                favor_precision=True) or ""
        except Exception:  # noqa: BLE001  - never let extraction break collection
            body = ""
    if not body:
        body = _fallback_body(page_html)
    return {"title": title, "body": body.strip(), "lang": lang}


def summarise(body: str, *, limit: int = 320) -> str:
    """A first-paragraph extract. Not a model summary and never presented as one."""
    body = (body or "").strip()
    if not body:
        return ""
    first = next((p.strip() for p in body.split("\n") if len(p.strip()) > 40), body)
    if len(first) <= limit:
        return first
    cut = first[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"
