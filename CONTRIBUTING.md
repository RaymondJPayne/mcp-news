# Contributing

The architecture exists to make contribution cheap. Six extension points, each a
class plus a decorator, each testable with a fixture and no network.

## Extension points

| You want to add | Implement | Where |
|---|---|---|
| A new kind of feed | `SourceAdapter` | `src/mcpnews/sources/adapters/` |
| A chat or embedding engine | `ChatProvider` / `EmbedProvider` | `src/mcpnews/providers/adapters/` |
| A pipeline step | `EnrichStep` | `src/mcpnews/enrich/steps/` |
| A scoring rule type | `RuleType` | `src/mcpnews/rank/rules.py` |
| A storage backend | `ArticleStore` | `src/mcpnews/store/backends/` |
| A trend detector | `Detector` | `src/mcpnews/signals/detectors/` |

Each registry validates at startup, so a typo in config is a clear error naming
the valid options — not a stack trace on first use.

## Rules that keep the project coherent

**No capability may become mandatory.** If your feature needs a model, it belongs
in `enrich/` behind a tier check, and the system must remain useful without it.
This is the constraint most likely to be violated by accident.

**Never merge relevance and recency.** The stored score is interest only. Decay is
a query-time parameter. `tests/test_scoring_invariants.py` pins this and will fail
your PR if it changes.

**Archive before you judge.** Any code path that fetches article text writes it to
the archive before any relevance decision. Discarding on first fetch is
irreversible.

**No third-party UI frameworks or hosted assets.** The dashboard is hand-written
HTML, CSS and vanilla JavaScript, served from our own origin. No CDN, no vendor
banner, no analytics, no telemetry, no fonts fetched from someone else's server.
A PR adding a framework, a tracker or a remote asset will be declined regardless
of how much nicer it looks.

**Adapters do not make decisions.** A source adapter returns candidates. It does
not score, filter, deduplicate or call a model. Keeping this boundary sharp is
why adapters stay ~60 lines.

## Adding a source to the shipped bundles

See [`docs/SOURCES.md`](docs/SOURCES.md) §5. In short: a real feed endpoint,
correct `lang` and `region`, an honest `interval_min`, and today's date in
`added` and `verified`. Regional and non-English bundles are especially wanted —
the default list leans English and North American, and that is a limitation to
fix rather than a design.

## Development

```bash
uv sync                 # install
uv run pytest           # tests
uv run ruff check .     # lint
uv run mcpnews --help   # CLI
docker compose up       # the whole thing
```

Tests must not require network, an API key, or a GPU. Provider and adapter tests
run against fixtures and a fake provider.

## Code of conduct

Be decent. Assume good faith. Disagree about the work, not the person.
