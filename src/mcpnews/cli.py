"""Command line entry point.

    mcpnews serve --all          run collector, enricher and server
    mcpnews collect              one collection pass
    mcpnews enrich --backlog     process everything pending, best first
    mcpnews rescore              re-rank the corpus after a profile edit
    mcpnews sources check        report failing or expired sources
    mcpnews explain <id>         show why an article scored what it did
    mcpnews mcp                  run the MCP server on stdio
    mcpnews status               corpus size, tier, provider health
"""
import typer

app = typer.Typer(add_completion=False, help="Self-hosted news, ranked by a file you wrote.")


@app.command()
def status() -> None:
    """Corpus size, capability tier and provider health."""
    raise NotImplementedError("phase 1")


if __name__ == "__main__":
    app()
