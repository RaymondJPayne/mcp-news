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
| A database backend | `ArticleStore` | `src/mcpnews/store/backends/` |
| An archive backend | `BlobStorage` | `src/mcpnews/storage/backends/` |
| A language | a JSON file | `web/i18n/` |

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

**No user-visible English in code.** Every string a reader can see comes from
`web/i18n/<lang>.json`. Templates, JavaScript and API responses all obey this: an
API error is `{"error": {"key": "err.source.unreachable", "params": {}}}` and the
browser renders it in the reader's language. Add a key to `en.json` in the same
change that adds the code path — `tests/test_i18n_parity.py` and
`tests/test_api.py` both fail otherwise. Retrofitting this is the single most
expensive mistake available in this codebase, which is why it is a rule rather
than a preference. See [`docs/LOCALIZATION.md`](docs/LOCALIZATION.md).

**Nothing on the happy path may require a text editor.** If your feature needs
configuration, it needs a control in the dashboard and a line of help text
explaining it to somebody who has never heard of the thing it configures. The
YAML files exist so the reader owns their configuration, not so they have to
type it.

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
uv run mcpnews serve    # the dashboard on http://127.0.0.1:8378
docker compose up       # the whole thing
```

Running from a source checkout puts configuration in `./config`, the database in
`./data` and the archive in `./data/archive`. Set `MCPNEWS_CONFIG_DIR`,
`MCPNEWS_DATA_DIR` or `MCPNEWS_ARCHIVE_DIR` to work against a scratch copy.

Tests must not require network, an API key, or a GPU. Provider and adapter tests
run against fixtures and a fake provider.

## Code of conduct

Be decent. Assume good faith. Disagree about the work, not the person.
