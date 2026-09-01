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
decision is taken. This is deliberate: what is not captured on first fetch is
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
| Archive | gzipped rows in monthly SQLite files | object storage |
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
| Signal detector | `Detector` | `signals/registry.py` |

See [`CONTRIBUTING.md`](../CONTRIBUTING.md).
