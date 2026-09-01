# MCP tool surface

The MCP server is the primary interface, not a wrapper bolted on afterwards.

Run: `mcpnews mcp` (stdio) or `mcpnews mcp --http --port 8379`.

Every tool degrades honestly. If semantic search is unavailable because no embed
provider is configured, `search` returns keyword results and says so in
`mode: "keyword"` — it does not silently return worse answers.

## Tools

| Tool | Purpose |
|---|---|
| `search` | Find articles by meaning and keyword. |
| `for_me` | The reader's ranked feed, with the rules that fired. |
| `ask` | A cited answer synthesised from the corpus. Needs a chat provider. |
| `brief` | What changed recently — accelerating topics, new entity pairings. |
| `article` | Full stored text of one article, including archived copies. |
| `timeline` | Mention volume for a term over time. |
| `entity` | What is known about a named entity and what it connects to. |
| `sources` | List configured sources with health and lifecycle status. |
| `profile` | Read the active profile, or explain a score. |
| `status` | Corpus size, tier, provider health, queue depth. |

Two of these are not implemented yet and say so rather than guessing: `brief` and
`entity` return an empty result with an explicit note, because they depend on
entity extraction and change detection. See [`ROADMAP.md`](ROADMAP.md).

## Signatures

```python
search(query: str, limit: int = 20, days: int = 90,
       lang: str | None = None, mode: "auto"|"semantic"|"keyword" = "auto")
  -> {results: [{article_id, title, title_translated, url, domain,
                 published_at, score, snippet}], mode: str, count: int}

for_me(hours: int = 72, limit: int = 30, section: str | None = None,
       half_life_h: float | None = None)
  -> {items: [{article_id, title, url, domain, published_at,
               interest_score, matched_rules: [{name, weight, in_title}],
               summary}], threshold: float, tier: int}

ask(question: str, days: int = 30, limit: int = 12)
  -> {answer: str | None, sources: [...], note: str | None}
     # answer is null with an explanatory note when no chat provider is reachable

brief(hours: int = 24, top: int = 12)
  -> {items: [{subject, kind, score, evidence, articles: [...]}]}

article(article_id: int, include_body: bool = True)
  -> {article_id, title, url, domain, published_at, lang, body,
      source: "live"|"archive", enrichment_state: {...}}

timeline(term: str, days: int = 90, bucket: "hour"|"day" = "day")
  -> {term, points: [{t, count}], trend: {direction, change_pct}}

entity(name: str, days: int = 90)
  -> {found: bool, entity: {...}, series: [...], relations: [...], articles: [...]}

sources(status: str | None = None)
  -> {sources: [{id, name, kind, status, last_ok_at, consecutive_failures,
                 verified, expires, article_count}]}

profile(explain_article_id: int | None = None)
  -> {profile: {...}} | {article_id, total, rules: [{name, points, hits}]}

status()
  -> {articles, enriched, queued, tier, providers: [{slot, state, last_ok}],
      sources_active, sources_failing}
```

## Design notes

**Citations are structural.** `ask` returns `sources` alongside `answer`, and the
prompt requires a `[n]` marker per claim. An answer without traceable sources is
a failure, not a stylistic preference.

**No tool writes article content.** The MCP surface is read-only over the corpus.
`profile` reads; it does not edit. Configuration changes go through the CLI or the
dashboard, where a human sees them.

**Transports.** `mcpnews mcp` speaks stdio; `mcpnews mcp --http --port 8379`
serves streamable HTTP. Both run the same tools over the same store.

**`status` exists so assistants can explain themselves.** When a reader asks why
an answer was thin, the assistant can check the tier and queue depth and say
"you have 4,000 articles pending embedding" instead of guessing.
