"""URL canonicalisation.

Two links to the same article should be the same string before deduplication
ever gets involved, because the cheapest duplicate to catch is the one that is
literally identical. Everything here is conservative: a transformation that
might change *which page* you get is not applied.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

#: Parameters that identify a campaign, not a document. Stripping them is safe;
#: keeping them means the same article arrives four times from four newsletters.
_TRACKING_EXACT = {
    "gclid", "gclsrc", "dclid", "fbclid", "msclkid", "twclid", "igshid", "mc_cid",
    "mc_eid", "yclid", "_hsenc", "_hsmi", "vero_id", "wickedid", "oly_enc_id",
    "oly_anon_id", "ref_src", "ref_url", "cmpid", "ncid", "spm", "at_medium",
    "at_campaign", "at_custom1", "at_custom2", "at_custom3", "at_custom4",
    "smid", "smtyp", "partner", "sh",
}
_TRACKING_PREFIXES = ("utm_", "pk_", "piwik_", "matomo_", "hsa_", "ito", "ir_")

_DEFAULT_PORTS = {"http": "80", "https": "443"}
_INDEX_SUFFIX = re.compile(r"/(index|default)\.(html?|php|aspx?)$", re.IGNORECASE)


def _keep(param: str) -> bool:
    low = param.lower()
    if low in _TRACKING_EXACT:
        return False
    return not any(low.startswith(p) for p in _TRACKING_PREFIXES)


def canonicalise(url: str) -> str:
    """Return a stable form of ``url``. Raises ValueError on anything unusable."""
    url = (url or "").strip()
    if not url:
        raise ValueError("empty url")
    if url.startswith("//"):
        url = "https:" + url
    if "://" not in url:
        url = "https://" + url

    parts = urlsplit(url)
    scheme = (parts.scheme or "https").lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme {scheme!r}")

    host = (parts.hostname or "").lower().rstrip(".")
    if not host or "." not in host and host != "localhost":
        raise ValueError(f"unusable host in {url!r}")
    # www is an alias for the apex in practice for every publisher we collect from.
    if host.startswith("www."):
        host = host[4:]

    netloc = host
    if parts.port and str(parts.port) != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{parts.port}"

    path = parts.path or "/"
    path = _INDEX_SUFFIX.sub("/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"

    query = urlencode(
        sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if _keep(k)))

    # Fragments address a position within a document, never a different document.
    return urlunsplit((scheme, netloc, path, query, ""))


def domain_of(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def is_probably_url(value: str) -> bool:
    try:
        canonicalise(value)
    except ValueError:
        return False
    return True
