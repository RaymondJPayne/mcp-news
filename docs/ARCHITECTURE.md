# Architecture

Five stages, each independently runnable, each able to make progress when the one
after it is unavailable. That property is the design — not a nice-to-have.

```
  sources/*.yaml
        │
        ▼
   ┌─────────┐   candidates    ┌─────────┐   articles   ┌──────────┐
   │ COLLECT │ ──────────────► │  STORE  │ ───────────► │   RANK   │
   └─────────┘                 └─────────┘              └──────────┘
        │                           ▲                        │
        │ full text                 │ enrichment             │ scored
        ▼                           │                        ▼
   ┌─────────┐                 ┌─────────┐              ┌──────────┐
   │ ARCHIVE │                 │ ENRICH  │◄─── models   │  SERVE   │
   └─────────┘                 └─────────┘   (optional) └──────────┘
                                                          │      │
                                                        API    MCP
```

## The stages

**COLLECT** reads `config/sources/*.yaml`, polls what is due, and produces
*candidates* — url, title, published date, language, whatever metadata the feed
carried. Adapters do no I/O beyond their own fetch and make no judgements. A
candidate is not yet an article.

**STORE** canonicalises the URL, checks whether we have seen it, fetches the body
when the feed did not carry one, extracts readable text, computes a SimHash for
near-duplicate detection, and writes the article. Nothing here needs a model.

**ARCHIVE** writes the full text to durable storage *before* any relevance
decision is taken. Storage is behind `storage/base.py`, whose keys are logical
and `/`-separated rather than filesystem paths, so the root can be a bind-mounted
host directory on any operating system today and an object store later without
touching a caller. This is deliberate: what is not captured on first fetch is
often gone within weeks, and a reader who changes their interests later should not
be punished for what they cared about earlier.

**ENRICH** is the only stage that needs a model, and the only stage that is
optional. Embeddings, translation, per-article context, entities. Each capability
tracks its own state per article, so a corpus collected with no model at all can
be enriched months later, in relevance order.

**RANK** scores every article against `profile.yaml`. Pure string matching with
weights — no model, no training, no network. This is why Tier 0 is genuinely
useful rather than a placeholder.

**SERVE** exposes the result twice: a JSON API that the dashboard consumes, and an
MCP server that AI assistants consume. Both are thin readers over the same store.

## Two invariants worth stating

**Relevance and freshness are separate axes.** A stored `interest_score` reflects
only how well an article matches the reader's profile. Recency is applied at query
time as a view parameter, never baked into the stored score. Merging them means a
month-old article scores near zero regardless of how well it matches — which
silently destroys any historical query and any backfill. A test pins this.

**Cheap stages are never gated on expensive ones.** Fetching and storing cost
bandwidth and disk. Enrichment costs a GPU or an API bill. So the pipeline gates
enrichment on relevance, and never gates collection on anything. Collect
everything, understand selectively, revisit the decision later.

## Configuration, and who edits it

The dashboard is the primary editor. A reader completes a first-run wizard in the
browser — language, storage location, source bundles, interests — and every
settings screen afterwards writes the same files. Nothing on the path to a
working feed requires a text editor, an environment variable or a terminal.

The files are still plain YAML, and that is not a contradiction. Configuration
belongs to the reader: they should be able to read it, copy it to another
machine, keep it in version control and understand what it says. What they should
not have to do is type it.

| File | Written by | Holds |
|---|---|---|
| `config/settings.yaml` | wizard, Settings | language, storage paths, bundles, collection behaviour |
| `config/profile.yaml` | Interests screen | the entire ranking model |
| `config/providers.yaml` | Settings → AI models | slots, chains, failover. Never a key — only the name of the variable holding one |
| `config/sources/*.yaml` | shipped, plus the Sources screen | source intent and lifecycle dates |

A value present in `settings.yaml` wins over the environment. The environment
supplies the *defaults the wizard offers*, which is how a container gets sensible
starting paths without overriding a choice the reader made afterwards.

## Internationalisation

Every user-visible string lives in `web/i18n/<lang>.json`: one flat JSON object,
dot-path keys, `{named}` placeholders, no nesting and no compile step. The
browser merges English underneath the chosen locale, so a missing key degrades
instead of showing a raw key.

The server never sends an English sentence. API errors and notes are catalogue
keys with parameters — `{"error": {"key": "err.source.unreachable"}}` — and the
browser, which knows the reader's language, turns them into words. This is
structural rather than stylistic: an API that returns prose can only ever be
localised by translating the server, and by then it is far too late.

Right-to-left is handled by the `dir` attribute and logical CSS properties, not
by a second stylesheet. See [`LOCALIZATION.md`](LOCALIZATION.md).

## Storage

Default is a single SQLite file with FTS5 for keyword search and `sqlite-vec` for
vectors. One file, no services, works on a laptop and on a Pi.

Both are behind interfaces (`store/base.py`, `search/base.py`) with adapters, so a
larger deployment can swap in Postgres and Qdrant without touching the pipeline.
The default is deliberately the humble one — a project that requires four
containers to see its first article has already lost most of its potential users.

| Concern | Default | Scale option |
|---|---|---|
| Articles, sources, state | SQLite | PostgreSQL |
| Keyword search | SQLite FTS5 | PostgreSQL FTS |
| Vectors | sqlite-vec | Qdrant |
| Archive | gzipped JSON in monthly directories | object storage, Drive, Dropbox |
| Graph | edge table in SQL | Neo4j |

## Processes

One container by default, running a supervisor over three loops — collector,
enricher, server. `PROFILE=split` in compose runs them as separate services when
you want to give the enricher its own resource limits.

## Extension points

Everything a contributor is likely to want to add is a registered class:

| Point | Interface | Registry |
|---|---|---|
| Source type | `SourceAdapter` | `sources/registry.py` |
| Chat / embed engine | `ChatProvider` / `EmbedProvider` | `providers/registry.py` |
| Enrichment step | `EnrichStep` | `enrich/registry.py` |
| Scoring rule type | `RuleType` | `rank/rules.py` |
| Store backend | `ArticleStore` | `store/registry.py` |
| Archive backend | `BlobStorage` | `storage/registry.py` |
| Signal detector | `Detector` | `signals/registry.py` |

See [`CONTRIBUTING.md`](../CONTRIBUTING.md).
