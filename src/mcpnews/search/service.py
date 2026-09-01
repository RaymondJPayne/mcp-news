"""Retrieval, honest about which mode actually ran.

If semantic search is unavailable because no embedding provider is configured,
the result says ``mode: keyword`` and carries a note key explaining it. It does
not silently return worse answers and call them the same thing.
"""
from __future__ import annotations

import logging

from mcpnews.providers.chain import NoProviderAvailable
from mcpnews.search.base import SearchHit, SearchResult

log = logging.getLogger("mcpnews.search")

#: Reciprocal-rank fusion constant. 60 is the value the original paper uses and
#: the result is insensitive to it; it is here so the number is not a mystery.
_RRF_K = 60


def _hit(article, score: float, snippet: str = "") -> SearchHit:
    return SearchHit(
        article_id=article.id, title=article.title, url=article.url,
        domain=article.domain, published_at=article.published_at, score=score,
        snippet=snippet or article.summary[:240],
        title_translated=article.title_translated)


async def search(app, query: str, *, limit: int = 20, days: int | None = 90,
                 lang: str | None = None, mode: str = "auto") -> SearchResult:
    query = (query or "").strip()
    if not query:
        return SearchResult([], "keyword")

    keyword_hits = [_hit(a, rel, snip)
                    for a, rel, snip in app.store.keyword_search(
                        query, limit=limit * 2, days=days, lang=lang)]

    want_semantic = mode in ("auto", "semantic", "hybrid")
    if not want_semantic:
        return SearchResult(keyword_hits[:limit], "keyword")

    if not app.providers.has_embed():
        # Asked for semantic explicitly? Say plainly why it is not happening.
        note = "search.mode_note" if mode in ("semantic", "hybrid") else None
        return SearchResult(keyword_hits[:limit], "keyword", note_key=note)

    try:
        vectors, _slot, model_id = await app.providers.embed([query])
    except NoProviderAvailable:
        return SearchResult(keyword_hits[:limit], "keyword", note_key="err.provider.unreachable")
    except Exception as exc:
        log.info("semantic search unavailable: %s", exc)
        return SearchResult(keyword_hits[:limit], "keyword", note_key="err.provider.unreachable")

    semantic_hits = [_hit(a, sim) for a, sim in app.store.vector_search(
        vectors[0], model_id, limit=limit * 2, days=days)]

    if mode == "semantic":
        return SearchResult(semantic_hits[:limit], "semantic")
    if not semantic_hits:
        return SearchResult(keyword_hits[:limit], "keyword")

    # Reciprocal-rank fusion: no score normalisation between two incomparable
    # scales, and a document both lists agree on rises to the top.
    ranks: dict[int, float] = {}
    seen: dict[int, SearchHit] = {}
    for ranking in (keyword_hits, semantic_hits):
        for position, hit in enumerate(ranking, start=1):
            ranks[hit.article_id] = ranks.get(hit.article_id, 0.0) + 1.0 / (_RRF_K + position)
            seen.setdefault(hit.article_id, hit)
    fused = sorted(seen.values(), key=lambda h: ranks[h.article_id], reverse=True)
    for hit in fused:
        hit.score = round(ranks[hit.article_id], 6)
    return SearchResult(fused[:limit], "hybrid")
