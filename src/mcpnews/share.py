"""Sharing an article means sharing the publisher's link. Nothing else.

Three properties are load-bearing here, and each one is easy to lose in a later
edit:

* **The link that leaves this machine is the source link.** Never the local copy,
  never a ``localhost`` address, never an article id from our own database. An
  article with no usable source link produces no payload at all, and the
  dashboard renders no control for it.
* **Every share intent is a plain URL.** No vendor SDK, no embedded widget, no
  remote script, no tracking pixel. A share is a link the reader's browser opens
  in a new tab, and the platform sees exactly what any pasted link would show.
* **Composition happens here, not in the browser.** The templates below are the
  single place a share URL is built, so a test can prove what each platform
  receives. The dashboard substitutes at most one remaining placeholder — the
  reader's Mastodon server, which only the browser knows.

The text is deliberately short. The tightest platform in the list still counts to
roughly 280 characters, so everything is composed to fit that; when it does not
fit, the *title* is truncated and the URLs are left whole. A truncated link is
worthless, a truncated headline is still a headline.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

# The tightest mainstream limit. Composing to it means one payload works
# everywhere rather than nine payloads that each work in one place.
MAX_LENGTH = 280

# Below this there is no point showing a headline at all; the link alone is more
# use to a reader than four words and an ellipsis.
MIN_TITLE = 16

ELLIPSIS = "…"

#: The default attribution text is a catalogue key, not a sentence, so the line
#: the reader posts is in the reader's own language.
ATTRIBUTION_TEXT_KEY = "share.attribution.default_text"

_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

_LOCAL_HOSTS = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".test")


@dataclass(frozen=True)
class ShareTarget:
    """One platform's share-intent URL.

    ``template`` is substituted with percent-encoded values for ``{url}``,
    ``{title}``, ``{text}`` and ``{text_only}``. ``{instance}`` is left in place
    when the reader has not told us their server yet: the browser fills it in and
    remembers the answer, because their Mastodon server is theirs to know.

    ``carries_text`` is false where the platform accepts only a link and composes
    its own preview. The attribution line cannot travel with those, which the
    Settings help says plainly rather than pretending otherwise.
    """

    id: str
    template: str
    carries_text: bool = True
    needs_instance: bool = False


#: Order matters: this is the order the fallback menu shows.
TARGETS: tuple[ShareTarget, ...] = (
    ShareTarget("mastodon", "https://{instance}/share?text={text}", needs_instance=True),
    ShareTarget("bluesky", "https://bsky.app/intent/compose?text={text}"),
    ShareTarget("linkedin",
                "https://www.linkedin.com/sharing/share-offsite/?url={url}",
                carries_text=False),
    ShareTarget("reddit", "https://www.reddit.com/submit?url={url}&title={title}",
                carries_text=False),
    ShareTarget("whatsapp", "https://wa.me/?text={text}"),
    ShareTarget("telegram", "https://t.me/share/url?url={url}&text={text_only}"),
    ShareTarget("facebook", "https://www.facebook.com/sharer/sharer.php?u={url}",
                carries_text=False),
    ShareTarget("x", "https://x.com/intent/post?url={url}&text={text_only}"),
    ShareTarget("email", "mailto:?subject={title}&body={text}"),
)

TARGET_IDS = tuple(target.id for target in TARGETS)


def is_shareable(url: str) -> bool:
    """Is this a link worth sending to someone else?

    False for anything empty, anything that is not http(s), and anything that
    only resolves on this machine or this network — which is the guard that stops
    a local copy from ever being shared, whatever else changes upstream.
    """
    if not url or not url.strip():
        return False
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    host = parts.hostname.lower()
    if host in _LOCAL_HOSTS or host.endswith(_LOCAL_SUFFIXES):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # A name, not an address. It has to look like a public hostname.
        return bool(_HOST.match(host))
    return not (address.is_loopback or address.is_private or address.is_link_local
                or address.is_reserved or address.is_unspecified)


def normalise_instance(value: str) -> str:
    """A Mastodon server as a bare hostname, or empty if it is not one.

    Readers type ``https://mastodon.social/@me`` as often as ``mastodon.social``.
    """
    host = (value or "").strip().lower()
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", host)
    host = host.split("/")[0].split("@")[-1].split(":")[0]
    return host if _HOST.match(host) else ""


def _truncate(text: str, budget: int) -> str:
    if budget <= 0 or len(text) <= budget:
        return text if budget > 0 else ""
    if budget < MIN_TITLE:
        return ""
    cut = text[: budget - 1].rstrip()
    # Prefer a word boundary, but not at the cost of half the headline.
    space = cut.rfind(" ")
    if space >= int(budget * 0.6):
        cut = cut[:space].rstrip()
    return f"{cut}{ELLIPSIS}" if cut else ""


def attribution_line(text: str, url: str) -> str:
    """The credit line: words, then link. Either half may be empty."""
    return " ".join(part for part in ((text or "").strip(), (url or "").strip()) if part)


def compose(*, title: str, url: str, attribution: str = "",
            max_length: int = MAX_LENGTH) -> dict[str, str]:
    """Build the text a reader posts.

    ``text`` is the whole thing including the source link; ``text_only`` is the
    same without it, for the platforms that take the link as its own field and
    would otherwise show it twice.
    """
    title = " ".join((title or "").split())
    attribution = attribution.strip()
    url = url.strip()

    # Everything except the headline is fixed cost: URLs are never shortened.
    tail = [line for line in (url, attribution) if line]
    fixed = len("\n".join(tail)) + (1 if tail else 0)
    shown = _truncate(title, max_length - fixed)

    text = "\n".join(line for line in [shown, *tail] if line)
    text_only = "\n".join(line for line in (shown, attribution) if line)
    return {"url": url, "title": shown, "full_title": title,
            "text": text, "text_only": text_only, "attribution": attribution}


def href(target: ShareTarget, composed: dict[str, str], instance: str = "") -> str:
    """One platform's share URL.

    Values are percent-encoded with nothing left safe, so a headline containing
    ``&``, ``#`` or ``?`` cannot break out of the parameter it sits in.
    """
    values = {
        "url": quote(composed["url"], safe=""),
        "title": quote(composed["title"] or composed["url"], safe=""),
        "text": quote(composed["text"], safe=""),
        "text_only": quote(composed["text_only"], safe=""),
    }
    if target.needs_instance:
        host = normalise_instance(instance)
        # Left as a literal placeholder when unknown: the browser asks the reader
        # once and remembers the answer.
        if host:
            values["instance"] = host
    out = target.template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out


def payload(*, url: str, title: str, attribution: str = "",
            max_length: int = MAX_LENGTH) -> dict | None:
    """What the dashboard needs to offer the system share sheet, or None.

    None means the article has no link worth sharing, and the dashboard renders
    no control at all rather than a control that cannot work.
    """
    if not is_shareable(url):
        return None
    composed = compose(title=title, url=url, attribution=attribution,
                       max_length=max_length)
    return {"url": composed["url"], "title": composed["title"],
            "text": composed["text"], "text_only": composed["text_only"],
            "attribution": composed["attribution"]}


def targets(*, url: str, title: str, attribution: str = "", instance: str = "",
            max_length: int = MAX_LENGTH) -> list[dict] | None:
    """Every fallback target, ready to open. None when there is nothing to share."""
    if not is_shareable(url):
        return None
    composed = compose(title=title, url=url, attribution=attribution,
                       max_length=max_length)
    return [{"id": target.id, "href": href(target, composed, instance),
             "carries_text": target.carries_text} for target in TARGETS]
