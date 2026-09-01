# Roadmap

Each phase ends at something a person can actually use. No phase is scaffolding
for a later phase only.

## Phase 0 — Scaffold *(current)*

Repo structure, interfaces, configuration schemas, docs, Docker skeleton.

**Done when:** `docker compose up` starts, `/api/health` responds, the test suite
runs green against stub implementations.

## Phase 1 — Collect

Source loading from YAML with lifecycle handling. RSS, Atom and JSON Feed
adapters. URL canonicalisation, body extraction, SimHash dedup, SQLite store.
Full-text keyword search.

**Done when:** it collects from the shipped bundles for a week unattended, and
`mcpnews search "term"` returns sensible results. **No model involved.**

## Phase 2 — Rank

Profile loading and validation. Rule matching with word boundaries, weights,
caps, `must_include`, mute. Score explanation. Query-time recency as a view.

**Done when:** `for_me` returns a ranked feed and `explain` shows exactly why each
item is there. Still no model.

## Phase 3 — Serve

The JSON API and the hand-written dashboard: feed, search, article view, source
management, profile editor with live re-rank. Responsive, installable as a PWA.

**Done when:** a reader can use this daily on a phone with no AI configured.

## Phase 4 — MCP

Full tool surface, honest degradation, stdio and HTTP transports.

**Done when:** an assistant answers a real question against the corpus, with
citations, and correctly reports which tier it is operating in.

## Phase 5 — Enrich

Provider registry, four default slots, chains and circuit-breaker failover.
Embeddings and hybrid search. Translation. Per-article context. Backlog
processing in relevance order.

**Done when:** a corpus collected in Phase 1 with no model can be fully enriched
later by one command, and the system survives a provider going down mid-run.

## Phase 6 — Understand

Entity extraction, relationship edges, clustering, velocity and change detection,
`brief` and `timeline` with real signal rather than raw counts.

**Done when:** `brief` surfaces something a reader would not have found by
scrolling, and can show the evidence for it.

## Phase 7 — Archive and history

Durable full-text archive separate from the working store. Historical backfill for
sources that expose it. Re-scoring an archived corpus against an edited profile
without re-fetching.

**Done when:** changing `profile.yaml` re-ranks the entire history offline.

---

## Deliberately not scheduled

**Sharing an index between installations.** A future capability, not a Phase 8. It
would need its own design, its own opt-in, and its own careful thought about what
is and is not appropriate to transmit. The current architecture keeps everything
local to the reader who collected it, and nothing in the roadmap above assumes
otherwise. Interfaces are kept clean enough that it stays possible.
