"""The MCP server. Primary interface, not an afterthought.

Every tool degrades honestly. If semantic search is unavailable because no embed
provider is configured, ``search`` returns keyword results and says so in
``mode: "keyword"`` — it does not silently return worse answers. ``ask`` returns
a null answer with an explanation rather than inventing one.

No tool writes article content. Configuration changes go through the dashboard
or the CLI, where a human sees them.
"""
from __future__ import annotations

import asyncio

from mcpnews import __version__
from mcpnews.providers.chain import NoProviderAvailable
from mcpnews.runtime import App, ensure_config_files
from mcpnews.search.service import search as run_search
from mcpnews.search.views import display_score
from mcpnews.sources import loader

INSTRUCTIONS = (
    "Read-only access to the reader's own locally collected news corpus. "
    "Results are ranked by a profile the reader wrote and can read. "
    "Check status() when an answer seems thin: the capability tier and the "
    "enrichment queue usually explain why."
)

_NOT_YET = ("Not implemented in this release. Entity extraction and change "
            "detection land in a later phase; see docs/ROADMAP.md.")


def _mcp_server_class():
    """The SDK renamed FastMCP to MCPServer in version 2. Support both."""
    try:
        from mcp.server.mcpserver import MCPServer
        return MCPServer
    except ImportError:  # pragma: no cover - only on the older SDK
        from mcp.server.fastmcp import FastMCP
        return FastMCP


def _server(ctx: App):
    MCPServer = _mcp_server_class()

    server = MCPServer(name="mcp-news", version=__version__, instructions=INSTRUCTIONS)

    @server.tool()
    async def search(query: str, limit: int = 20, days: int = 90,
                     lang: str | None = None, mode: str = "auto") -> dict:
        """Find articles by meaning and keyword."""
        result = await run_search(ctx, query, limit=limit, days=days or None,
                                  lang=lang, mode=mode)
        return {"results": [h.to_dict() for h in result.hits], "mode": result.mode,
                "count": len(result.hits)}

    @server.tool()
    async def for_me(hours: int = 72, limit: int = 30, section: str | None = None,
                     half_life_h: float | None = None) -> dict:
        """The reader's ranked feed, with the rules that fired on each item."""
        hl = ctx.profile.scoring.default_half_life_h if half_life_h is None else half_life_h
        articles = ctx.store.feed(hours=hours, limit=limit,
                                  min_score=ctx.profile.scoring.min_score, half_life_h=hl)
        items = []
        for a in articles:
            if section and not any(r.get("section") == section for r in a.matched_rules):
                continue
            items.append({
                "article_id": a.id, "title": a.title, "url": a.url, "domain": a.domain,
                "published_at": a.published_at, "interest_score": a.interest_score,
                "display_score": round(display_score(
                    a.interest_score, a.published_at or a.fetched_at, hl), 3),
                "matched_rules": a.matched_rules, "summary": a.summary,
            })
        return {"items": items, "threshold": ctx.profile.scoring.min_score, "tier": ctx.tier()}

    @server.tool()
    async def ask(question: str, days: int = 30, limit: int = 12) -> dict:
        """A cited answer synthesised from the corpus. Needs a chat provider."""
        result = await run_search(ctx, question, limit=limit, days=days or None)
        sources = [h.to_dict() for h in result.hits]
        if not ctx.providers.has_chat():
            return {"answer": None, "sources": sources,
                    "note": "No chat provider is configured, so no answer was synthesised. "
                            "The sources below are the corpus material for this question."}
        if not sources:
            return {"answer": None, "sources": [], "note": "Nothing in the corpus matched."}

        context = "\n\n".join(
            f"[{i}] {s['title']} — {s['domain']} ({s['published_at']})\n{s['snippet']}"
            for i, s in enumerate(sources, start=1))
        messages = [
            {"role": "system", "content":
                "Answer only from the numbered sources. Put a [n] marker on every claim. "
                "If the sources do not answer the question, say so plainly."},
            {"role": "user", "content": f"{question}\n\nSources:\n{context}"},
        ]
        try:
            answer, slot = await ctx.providers.chat(messages)
        except NoProviderAvailable:
            return {"answer": None, "sources": sources,
                    "note": "Every configured chat provider was unreachable."}
        return {"answer": answer, "sources": sources, "note": None, "provider": slot}

    @server.tool()
    async def brief(hours: int = 24, top: int = 12) -> dict:
        """What changed recently. Signal detection is not implemented yet."""
        return {"items": [], "note": _NOT_YET}

    @server.tool()
    async def article(article_id: int, include_body: bool = True) -> dict:
        """Full stored text of one article, including the archived copy."""
        record = ctx.store.get_article(article_id)
        if record is None:
            return {"error": "not found", "article_id": article_id}
        data = record.to_dict(include_body=include_body)
        data["source"] = "live"
        if include_body and not record.body and record.archive_ref:
            archived = ctx.archive.read(record.archive_ref)
            if archived:
                data["body"] = archived.get("body", "")
                data["source"] = "archive"
        return data

    @server.tool()
    async def timeline(term: str, days: int = 90, bucket: str = "day") -> dict:
        """Mention volume for a term over time."""
        points = ctx.store.timeline(term, days=days, bucket=bucket)
        counts = [n for _, n in points]
        half = max(1, len(counts) // 2)
        earlier, later = sum(counts[:half]) or 0, sum(counts[half:]) or 0
        change = ((later - earlier) / earlier * 100) if earlier else None
        direction = "flat" if change is None or abs(change) < 10 else (
            "rising" if change > 0 else "falling")
        return {"term": term, "points": [{"t": t, "count": n} for t, n in points],
                "trend": {"direction": direction,
                          "change_pct": round(change, 1) if change is not None else None}}

    @server.tool()
    async def entity(name: str, days: int = 90) -> dict:
        """What is known about a named entity. Extraction is not implemented yet."""
        return {"found": False, "note": _NOT_YET}

    @server.tool()
    async def sources(status: str | None = None) -> dict:
        """Configured sources with health and lifecycle status."""
        report = loader.check(ctx.store)
        rows = report["sources"]
        if status:
            rows = [r for r in rows if r["status"] == status]
        return {"sources": rows, "ok": report["ok"], "failing": report["failing"],
                "expired": report["expired"]}

    @server.tool()
    async def profile(explain_article_id: int | None = None) -> dict:
        """Read the active profile, or explain one article's score."""
        if explain_article_id is None:
            return {"profile": ctx.profile.to_dict()}
        record = ctx.store.get_article(explain_article_id)
        if record is None:
            return {"error": "not found", "article_id": explain_article_id}
        score = ctx.scorer.score(record.title, record.body or record.summary,
                                 record.domain, {"summary": record.summary})
        return {"article_id": explain_article_id, "total": score.total,
                "rules": [r.to_dict() for r in score.rules]}

    @server.tool()
    async def status_() -> dict:
        """Corpus size, tier, provider health and queue depth."""
        return ctx.status()

    # The tool is named "status" in the documented surface; the Python name only
    # avoids shadowing the parameter used by sources().
    try:
        server.remove_tool("status_")
        server.add_tool(status_, name="status",
                        description="Corpus size, tier, provider health and queue depth.")
    except Exception:
        pass

    return server


def build(ctx: App | None = None):
    ensure_config_files()
    return _server(ctx or App.create())


def run(*, http: bool = False, port: int = 8379) -> None:
    server = build()
    if http:
        asyncio.run(server.run_streamable_http_async(port=port))
    else:
        server.run(transport="stdio")
