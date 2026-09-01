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

**Sharing, on Today and on the article view.** What leaves this machine is the
publisher's link and nothing else: the payload is composed in `mcpnews/share.py`
from the article's source URL alone, so a local address, a private-network
address or an article id cannot reach a share target, and an article without a
source link renders no control at all. The primary path is the Web Share API,
which hands the reader their own operating system's share sheet and therefore
every application they have installed. Browsers without it get an explicit list —
Mastodon, Bluesky, LinkedIn, Reddit, WhatsApp, Telegram, Facebook, X, email and
Copy link — as plain share-intent URLs opened in a new tab, with no vendor SDK,
embedded widget, remote script or tracking pixel anywhere, and with icons drawn
inline as SVG that inherits `currentColor`. Copy link falls back to
`document.execCommand("copy")` where the asynchronous clipboard is unavailable,
which is how it works over plain HTTP on a home network. The menu is keyboard
navigable and closes on Escape and on an outside click. The reader's Mastodon
server is remembered by their browser and by nothing else; Settings shows it and
can forget it.

**Settings → Sharing.** An attribution line, on by default, with a plain editable
link and wording. Turning it off turns it off; nothing re-enables it. The wording
defaults to a catalogue string, so the line a reader posts is in their own
language, and the screen says plainly which platforms accept a link only and
therefore drop the line.

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
