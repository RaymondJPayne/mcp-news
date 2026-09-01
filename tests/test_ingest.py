"""Canonicalisation, fingerprinting and extraction. No network, no fixtures beyond files."""
from __future__ import annotations

import pytest

from mcpnews.ingest.canonical import canonicalise, domain_of, is_probably_url
from mcpnews.ingest.extract import extract, strip_html, summarise
from mcpnews.ingest.simhash import DEFAULT_MAX_DISTANCE, distance, simhash


@pytest.mark.parametrize("raw,expected", [
    ("https://www.Example.com/Story/?utm_source=x&b=2&a=1#part",
     "https://example.com/Story?a=1&b=2"),
    ("http://example.com:80/a/", "http://example.com/a"),
    ("https://example.com/index.html", "https://example.com/"),
    ("example.com/x", "https://example.com/x"),
    ("https://example.com/a?fbclid=zzz", "https://example.com/a"),
])
def test_canonicalisation(raw, expected):
    assert canonicalise(raw) == expected


def test_canonicalisation_rejects_rubbish():
    for bad in ("", "not a url", "mailto:someone@example.com", "javascript:alert(1)"):
        with pytest.raises(ValueError):
            canonicalise(bad)
    assert not is_probably_url("not a url")


def test_domain_strips_www():
    assert domain_of("https://www.example.co.uk/a") == "example.co.uk"


#: One agency story, as two outlets would carry it: a different headline, two
#: phrases reworded. Short enough to read, long enough to be representative.
_WIRE = ("Export control rules tighten on lithography tools sold into several markets. "
         "Officials said the measures take effect next quarter and cover both new and "
         "refurbished equipment, with a licence required for each shipment. Industry "
         "groups warned that the paperwork burden would fall hardest on smaller "
         "suppliers, who lack dedicated compliance teams. A spokesperson for the ministry "
         "said the threshold had been set deliberately high to avoid catching routine "
         "maintenance parts. The rules were published on Friday and run to ninety pages.")
_WIRE_COPY = ("Lithography export curbs widen, ministry says. "
              + _WIRE.replace("Officials said", "Officials stated")
                     .replace("on Friday", "late on Friday"))
_UNRELATED = ("Municipal recycling collection schedules change next month across the "
              "county, with new bins issued to households in the eastern districts and a "
              "revised calendar published online. The council said the change would "
              "reduce lorry mileage and improve sorting rates for household plastics.")
_SAME_TOPIC = ("Semiconductor equipment makers reported record orders this quarter as "
               "customers rushed to secure lithography tools before new export rules take "
               "effect. Shares rose four per cent in early trading on the news.")


def test_simhash_is_stable():
    assert simhash(_WIRE) == simhash(_WIRE)      # stable across calls and processes
    assert simhash("") == 0


def test_simhash_separates_wire_copy_from_different_stories():
    """The threshold only means something if the gap either side of it is wide."""
    near = distance(simhash(_WIRE), simhash(_WIRE_COPY))
    far = distance(simhash(_WIRE), simhash(_UNRELATED))
    same_topic = distance(simhash(_WIRE), simhash(_SAME_TOPIC))
    assert near <= DEFAULT_MAX_DISTANCE
    # A different article on the same subject must not be treated as a copy.
    assert same_topic > DEFAULT_MAX_DISTANCE * 2
    assert far > DEFAULT_MAX_DISTANCE * 2


def test_extraction_drops_scripts_and_finds_the_article():
    html = """<html lang="pt"><head><title>A title</title>
    <script>var tracking = 1;</script><style>.a{}</style></head>
    <body><nav>Menu</nav><article><p>%s</p></article><footer>Legal</footer></body></html>
    """ % ("A sentence of genuine article text that is comfortably long enough to survive "
           "the short-line filter and be recognised as body copy. " * 3)
    got = extract(html, url="https://example.org/a")
    assert got["title"] == "A title"
    assert got["lang"] == "pt"
    assert "tracking" not in got["body"]
    assert "genuine article text" in got["body"]


def test_strip_html_unescapes_and_collapses():
    assert strip_html("<p>a &amp; b</p><p>c</p>") == "a & b\n\nc"


def test_summarise_truncates_on_a_word_boundary():
    text = "word " * 200
    out = summarise(text, limit=50)
    assert len(out) <= 51 and out.endswith("…")
