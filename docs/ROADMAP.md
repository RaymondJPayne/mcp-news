# Roadmap

Each phase ends at something a person can actually use. No phase is scaffolding
for a later phase only.

The state below is what the code does today, checked against the test suite
rather than against intent. Where a phase is partly done, it says which part.

## Phase 0 — Scaffold — **done**

Repo structure, interfaces, configuration schemas, docs, Docker skeleton.

**Done when:** `docker compose up` starts, `/api/health` responds, the test suite
runs green.

## Phase 1 — Collect — **done**

Source loading from YAML with lifecycle handling. RSS, Atom and JSON Feed
adapters — plus arXiv and news sitemaps, which are the same parsers with a
different query. URL canonicalisation, body extraction, SimHash dedup, SQLite
store, FTS5 keyword search, per-host politeness and `robots.txt`.

**Done when:** it collects from the shipped bundles unattended, and
`mcpnews search "term"` returns sensible results. **No model involved.**

*Not done:* the `html` adapter for feedless sites is registered and raises a
clear message rather than scraping. Deliberate — see docs/SOURCES.md §5.

## Phase 2 — Rank — **done**

Profile loading and validation. Rule matching with word boundaries, weights,
caps, `must_include`, `exclude`, mute, source boost and penalty. Score
explanation on every article. Query-time recency as a view, never stored.

**Done when:** `for_me` returns a ranked feed and `explain` shows exactly why
each item is there. Still no model. Pinned by
`tests/test_scoring_invariants.py`.

## Phase 3 — Serve — **done**

The JSON API and the hand-written dashboard: a first-run wizard, the ranked feed
with matched-rule chips, search, article view, source management with feed
testing, the interests editor with live preview, settings for everything, and
status. Internationalised from the first line, with English and Portuguese
complete. Responsive, installable as a PWA.

**Done when:** a reader can use this daily on a phone with no AI configured, and
never edits a file. That is the case.

*Not done:* the thumbs up and down described in docs/PROFILE.md, which would
produce suggested edits to the profile for the reader to accept or reject.

## Phase 4 — MCP — **mostly done**

The full documented tool surface runs over stdio and streamable HTTP. `search`
reports the mode it actually ran; `ask` synthesises a cited answer when a chat
provider is reachable and returns a null answer with an explanation when it is
not; `status` reports the tier and the queue so an assistant can explain itself.

*Not done:* `brief` and `entity` return an explicit "not implemented" note. They
depend on Phase 6 and inventing an answer would be worse than saying so.

## Phase 5 — Enrich — **partly done**

Done: the provider registry, four default slots, chains, circuit-breaker
failover with the documented state machine and failure classification, capability
tiers announced in `/api/status` and in the dashboard header, embeddings with
backlog processing in relevance order, and semantic and hybrid search over
vectors that record which model produced them.

*Not done:* translation, per-article context, and `mcpnews reindex --to <slot>`
for consolidating two vector spaces. The `translated` and `contextual`
enrichment states exist and stay `pending`.

**Done when:** a corpus collected in Phase 1 with no model can be fully enriched
later by one command. Embeddings meet that today; translation does not yet.

## Phase 6 — Understand — **not started**

Entity extraction, relationship edges, clustering beyond near-duplicates,
velocity and change detection, `brief` and `timeline` with real signal rather
than raw counts.

*Partly:* `timeline` returns real mention volume with a crude direction, over
FTS5 counts. It is honest, and it is not yet signal.

## Phase 7 — Archive and history — **partly done**

Done: the durable full-text archive, written before any relevance decision, in
monthly partitions behind a storage interface with a working local backend;
`mcpnews rescore` re-ranks the whole corpus against an edited profile with no
network and no model, which is the capability this phase exists for.

*Not done:* historical backfill for sources that expose it, and re-scoring
directly from archived text rather than from the working store.

---

## Deliberately not scheduled

**Sharing an index between installations.** A future capability, not a Phase 8.
It would need its own design, its own opt-in, and its own careful thought about
what is and is not appropriate to transmit. The current architecture keeps
everything local to the reader who collected it, and nothing in the roadmap above
assumes otherwise. Interfaces are kept clean enough that it stays possible.

## Known limitations, stated plainly

- **No authentication.** The server binds to localhost and this project ships no
  login and claims none. Putting it on a network is your reverse proxy's problem.
- **PostgreSQL and MySQL store backends are declared, not implemented.** They
  raise a message naming the working alternative. The interface was written
  against them so that implementing one is SQL rather than surgery.
- **S3, Dropbox, Google Drive and OneDrive archive backends are declared, not
  implemented.** `storage/backends/remote.py` records what each needs, including
  the OAuth flow, so the interface can be judged against them.
- **Vector search is a linear scan.** Correct, and fast enough for one reader's
  corpus. An ANN index belongs with the rest of Phase 5.
- **The shipped source bundles lean English and North American.** That is a
  limitation to fix, not a design. Regional bundles are welcome.
