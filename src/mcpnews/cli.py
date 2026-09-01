"""Command line entry point.

    mcpnews serve --all          run the collector, the enricher and the server
    mcpnews collect              one collection pass
    mcpnews enrich --backlog     process everything pending, best first
    mcpnews rescore              re-rank the corpus after a profile edit
    mcpnews sources check        report failing or expired sources
    mcpnews search <query>       keyword search from the terminal
    mcpnews explain <id>         show why an article scored what it did
    mcpnews mcp                  run the MCP server on stdio
    mcpnews status               corpus size, tier, provider health

The dashboard is the primary interface and nothing here is required to use the
product. These exist for scripting, for debugging and for people who prefer a
terminal.
"""
from __future__ import annotations

import asyncio
import json
import os

import typer

from mcpnews import __version__

app = typer.Typer(add_completion=False, help="Self-hosted news, ranked by rules you wrote.")
sources_app = typer.Typer(help="Inspect and check the source list.")
app.add_typer(sources_app, name="sources")


def _app():
    from mcpnews.runtime import App, ensure_config_files
    ensure_config_files()
    return App.create()


def _echo(data) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


@app.command()
def serve(
    all: bool = typer.Option(False, "--all", help="Also run the collector and enricher loops."),
    host: str = typer.Option("127.0.0.1", help="Bind address. Localhost by default: this "
                                               "application ships no authentication."),
    port: int = typer.Option(0, help="Port. Defaults to MCPNEWS_PORT or 8378."),
) -> None:
    """Run the HTTP server and the dashboard."""
    import uvicorn

    from mcpnews.api.app import create_app

    resolved_port = port or int(os.environ.get("MCPNEWS_PORT", "8378"))
    # In a container the loopback of the container is not reachable from the host,
    # so binding to all interfaces there is the only thing that works. The port is
    # still published to 127.0.0.1 on the host by compose.
    if os.path.exists("/.dockerenv") and host == "127.0.0.1":
        host = "0.0.0.0"
    uvicorn.run(create_app(collector_loop=all), host=host, port=resolved_port,
                log_level=os.environ.get("MCPNEWS_LOG_LEVEL", "info").lower())


@app.command()
def collect(source: list[str] = typer.Option(None, help="Only these source ids.")) -> None:
    """Run one collection pass."""
    from mcpnews.ingest.pipeline import Collector

    ctx = _app()
    if not ctx.configured:
        typer.echo("Setup has not been completed. Open the dashboard and finish the wizard.")
        raise typer.Exit(code=1)
    collector = Collector(ctx.settings, ctx.store, ctx.archive, ctx.profile)
    report = asyncio.run(collector.run_once(source_ids=list(source) if source else None))
    _echo(report.to_dict())


@app.command()
def enrich(backlog: bool = typer.Option(False, "--backlog", help="Process everything pending."),
           limit: int = typer.Option(200, help="Maximum articles in this run.")) -> None:
    """Process the enrichment backlog, highest interest score first."""
    from mcpnews.enrich import run_embeddings

    ctx = _app()
    report = asyncio.run(run_embeddings(ctx.store, ctx.providers,
                                        limit=100_000 if backlog else limit))
    _echo(report.to_dict())


@app.command()
def rescore() -> None:
    """Re-rank the whole corpus against the current profile. No model, no network."""
    from mcpnews.ingest.pipeline import rescore as run

    ctx = _app()
    _echo({"rescored": run(ctx.store, ctx.profile)})


@app.command()
def search(query: str, limit: int = 20, days: int = 90) -> None:
    """Search the corpus."""
    from mcpnews.search.service import search as run

    ctx = _app()
    result = asyncio.run(run(ctx, query, limit=limit, days=days))
    _echo({"mode": result.mode, "count": len(result.hits),
           "results": [h.to_dict() for h in result.hits]})


@app.command()
def explain(article_id: int) -> None:
    """Show exactly why an article scored what it did."""
    ctx = _app()
    record = ctx.store.get_article(article_id)
    if record is None:
        typer.echo("No such article.")
        raise typer.Exit(code=1)
    score = ctx.scorer.score(record.title, record.body or record.summary, record.domain,
                             {"summary": record.summary})
    _echo({"article_id": article_id, "title": record.title, "total": score.total,
           "explanation": score.explain(), "rules": [r.to_dict() for r in score.rules]})


@app.command()
def status() -> None:
    """Corpus size, capability tier and provider health."""
    _echo(_app().status())


@app.command()
def mcp(http: bool = typer.Option(False, "--http", help="Serve over HTTP instead of stdio."),
        port: int = typer.Option(8379)) -> None:
    """Run the MCP server."""
    from mcpnews.mcp.server import run

    run(http=http, port=port)


@sources_app.command("check")
def sources_check() -> None:
    """Report anything failing or past its review date."""
    from mcpnews.sources import loader

    ctx = _app()
    report = loader.check(ctx.store)
    _echo({"ok": report["ok"], "failing": report["failing"], "expired": report["expired"],
           "bundle_errors": report["bundle_errors"],
           "problems": [{"id": s["id"], "status": s["status"],
                         "consecutive_failures": s["consecutive_failures"],
                         "expired": s["expired"], "last_error": s["last_error"]}
                        for s in report["sources"] if s["failing"] or s["expired"]]})


@sources_app.command("list")
def sources_list() -> None:
    """Every registered source with its lifecycle state."""
    ctx = _app()
    _echo([s.to_dict() for s in ctx.store.list_sources()])


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
