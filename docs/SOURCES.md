# Sources: files, not a database table

Feeds rot. A URL that worked in 2024 redirects to a parking page in 2026; an
outlet moves from `/rss` to `/feed`; a government agency reorganises and the old
endpoint 404s silently for eight months before anyone notices. A source list that
lives only in a database is a source list nobody reviews.

So sources live in **version-controlled YAML files** under `config/sources/`, one
file per topical bundle, each entry carrying its own dates and lifecycle state.
The database holds *fetch state* — cursors, ETags, failure counts. The file holds
*intent*. They are different things and they are stored differently.

---

## 1. Layout

```
config/sources/
├── _schema.json            JSON Schema — validated in CI and at startup
├── core-world.yaml         general world news
├── gov-agency.yaml         government and agency feeds
├── tech-science.yaml       technology, research, security
├── business-finance.yaml   markets, regulation, filings
├── regional-latam.yaml     regional bundles, one file each
├── regional-europe.yaml
└── local.yaml              yours; gitignored, never overwritten by updates
```

`local.yaml` is the escape hatch: your private additions survive `git pull`
because the file is ignored. Everything else is shared and reviewable.

## 2. Entry format

```yaml
# config/sources/tech-science.yaml
version: 1
bundle: tech-science
description: Technology, research and security sources.
maintainer: community
updated: 2026-09-01

sources:
  - id: arxiv_cs_ai
    name: arXiv — Computing Research
    kind: arxiv                   # adapter id; see §4
    url: https://export.arxiv.org/api/query
    lang: en
    region: global
    topics: [ai, research]
    interval_min: 360

    # ---- lifecycle: the whole point of this file -------------------------
    status: active                # active | deprecated | dead | paused
    added: 2026-09-01             # when it entered the list
    verified: 2026-09-01          # last time a human or CI confirmed it works
    expires: 2027-09-01           # re-verify by this date or it goes stale
    # replaced_by: arxiv_cs_ai_v2 # set when status: deprecated
    # notes: "Moved to a new endpoint in Aug 2026."

    config:
      categories: [cs.AI, cs.LG, cs.CL, cs.CR]
      max_results: 100

  - id: cisa_kev
    name: CISA Known Exploited Vulnerabilities
    kind: json_feed
    url: https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json
    lang: en
    region: us
    topics: [security, government]
    interval_min: 120
    status: active
    added: 2026-09-01
    verified: 2026-09-01
    expires: 2027-09-01
```

### Field reference

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Stable, unique, lowercase. Never reuse an id for a different source. |
| `name` | yes | Human label shown in the UI. |
| `kind` | yes | Which adapter parses it. |
| `url` | yes | Endpoint. May contain `${ENV_VAR}` for keyed sources. |
| `lang` | yes | Source language, ISO 639-1, or `mixed`. Drives translation. |
| `region` | yes | ISO 3166-1 alpha-2, a region name, or `global`. Drives geo scoring. |
| `topics` | yes | Free tags. Used for bundle filtering and coverage reporting. |
| `interval_min` | yes | Politeness floor. The scheduler will not poll faster. |
| `status` | yes | See below. |
| `added` / `verified` / `expires` | yes | ISO dates. |
| `replaced_by` | when deprecated | `id` of the successor. |
| `notes` | no | Why it changed. Future you will want this. |
| `config` | no | Adapter-specific. |
| `auth` | no | `{api_key_env: NAME}`. Never a literal key. |

### Status lifecycle

```
   active ──── stops responding ────► dead
     │                                 │
     │ superseded                      │ fixed
     ▼                                 ▼
 deprecated ──── grace period ────► removed        paused ◄── user disabled
 (replaced_by set)                  (deleted)
```

- **`active`** — polled normally.
- **`paused`** — user disabled it in the dashboard. Not polled; kept in the file.
  Toggling in the UI writes back here, so a restart doesn't resurrect it.
- **`deprecated`** — still polled, but the UI shows a badge and points at
  `replaced_by`. Gives readers a window to migrate.
- **`dead`** — not polled. Kept as a tombstone so the id is never reused and the
  history explains itself.

### Expiry is a review prompt, not a deletion

`mcpnews sources check` reports anything where `expires` has passed or
`consecutive_failures` is climbing, and CI runs the same check weekly against the
shared bundles. A source past its expiry keeps working — it is flagged, not
disabled. The goal is that a stale list becomes *visible*, which is exactly what
a database table full of silently-404ing feeds never does.

## 3. Fetch state lives in the database

| Belongs in the file | Belongs in the database |
|---|---|
| id, name, url, kind, interval | cursor, ETag, `last_modified` |
| lang, region, topics | `last_run_at`, `last_ok_at` |
| status, dates, notes | `consecutive_failures`, `last_error` |
| adapter config | `next_allowed_at` |

One rule with teeth: **the loader never overwrites `status` from the file once a
source exists in the database.** The file sets the default at first registration;
after that the database is authoritative, because the user can toggle sources in
the dashboard. Without this rule every container restart silently re-enables
everything the reader turned off.

## 4. Adapters

| `kind` | Handles |
|---|---|
| `rss` | RSS 2.0, RDF |
| `atom` | Atom 1.0 |
| `json_feed` | JSON Feed 1.1 and plain JSON with a mapping |
| `sitemap` | News sitemaps |
| `arxiv` | arXiv Atom API with category filters |
| `html` | CSS/XPath extraction for feedless sites |

Adding one is a class and a decorator:

```python
from mcpnews.sources.base import SourceAdapter, register

@register("my_kind")
class MyAdapter(SourceAdapter):
    async def fetch(self, source, state) -> FetchResult:
        """Return FetchResult(items, cursor, etag).

        Each item is a CandidateItem: url, title, published_at, lang, raw_meta,
        and optionally body when the feed carries full text.
        """
```

Adapters return *candidates*. They never write to the database, never decide
relevance, and never call a model. That separation is what keeps them trivial to
contribute and trivial to test — a fixture file in, a list of candidates out.

## 5. Curation policy for the shared bundles

Pull requests adding sources to the shipped bundles are welcome. What gets merged:

- A stable, documented feed endpoint — not a scraped homepage.
- Correct `lang` and `region`. These drive real behaviour, not decoration.
- An honest `interval_min`. If the publisher states a rate limit, respect it.
- `added` and `verified` set to the date of the PR.

What does not:

- Sources requiring credentials the project would have to ship.
- Aggregators of other feeds already in the list — they duplicate the corpus and
  confuse deduplication.
- Anything whose robots.txt or terms disallow automated retrieval.

Regional and language bundles are especially welcome. The default list leans
English and North American, which is a limitation to fix, not a design.
