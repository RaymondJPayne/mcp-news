# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

**Setup and configuration through the browser.** A first-run wizard covering
language, storage location, source bundles and starter interests, and settings
screens for everything configurable: sources, interests, storage, providers and
collection behaviour. Every option carries contextual help written in plain
language. Configuration is written as readable YAML the reader owns, but the
dashboard is the primary editor and no file editing is required on the happy
path.

**Internationalisation, from the first line of interface code.** Flat JSON
catalogues at `web/i18n/<lang>.json` with stable dot-path keys and `{named}`
placeholders. Complete English and Portuguese locales, `_meta.json` describing
the format and tone, and `docs/LOCALIZATION.md`. API errors and notes are
catalogue keys rather than sentences, so no English reaches the browser from the
server. Right-to-left is a `dir` attribute; the stylesheet uses logical
properties throughout. Tests fail on a missing key, a mismatched placeholder or
a physical CSS direction property.

**Collection.** Dated source lifecycle loading with JSON Schema validation;
RSS, Atom, JSON Feed, arXiv and news sitemap adapters written against the
standard library; polite fetching with per-host spacing, conditional requests and
`robots.txt`; URL canonicalisation; readable-text extraction; SimHash
near-duplicate clustering; and a SQLite store with FTS5. The dashboard can test a
feed before adding it.

**Ranking.** The scorer from `docs/PROFILE.md` in full: word-boundary matching,
weights, `in_title_multiplier`, `cap_per_rule`, `must_include`, `exclude`, mute,
and source boost and penalty. The stored score is interest only; recency is a
query-time view. `mcpnews rescore` re-ranks the corpus after a profile edit with
no network and no model.

**Reading.** Today with matched-rule chips and a finite end, search that labels
the mode it actually ran, article view with the score explained, sources with
lifecycle badges, an interests editor with live preview, settings, and status.

**Architecture provisioned now rather than retrofitted.** A database abstraction
with a working SQLite backend and declared PostgreSQL and MySQL backends; a blob
storage abstraction with a working local-filesystem backend and declared S3,
Dropbox, Google Drive and OneDrive backends carrying their OAuth requirements;
the provider registry with chains, circuit-breaker failover and failure
classification; and capability tiers announced in the header and in
`/api/status`.

**MCP server.** The full documented tool surface over stdio and streamable HTTP,
degrading honestly: `ask` returns a null answer with an explanation when no chat
provider is reachable, and `brief` and `entity` say plainly that they are not
implemented yet.

**Enrichment.** Embeddings with backlog processing in relevance order, and
semantic and hybrid search over vectors that record which model produced them.
The store refuses to mix two vector spaces.

### Changed

- `docker compose up` works from a clean clone with no `.env` and no copied
  example configuration. The config directory is mounted read-write because the
  dashboard writes it; data and archive are bind mounts so a reader can find
  their own files.
- Dropped `feedparser` and made `trafilatura` optional. Feed parsing and text
  extraction are implemented against the standard library, which keeps the
  container small and the test suite free of a network.
- The `data/` and `archive/` ignore rules are anchored to the repository root;
  they were also excluding `src/mcpnews/archive/`.

### Not implemented

Stated here so the changelog does not imply more than the code does:
translation, per-article context, entity extraction, relationship edges, change
detection, `brief`, `entity`, the `html` source adapter, vector-space
consolidation, and the remote archive backends. See `docs/ROADMAP.md`.
