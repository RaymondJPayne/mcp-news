# mcp-news

**News for the reader — not news that turns the reader into the product.**

Your news feed is currently chosen by someone whose income depends on how long you
keep scrolling. `mcp-news` inverts that. You write down what you are interested
in, and that *is* the ranking algorithm — a list of rules you can read, stored in
a file you own. Nothing about you is transmitted anywhere, because there is
nowhere to transmit it to: the whole thing runs on your own machine.

You set it up in a browser. There is no file to edit, no environment variable to
export and no terminal to open on the way to a working feed. The configuration is
plain YAML because it is yours, not because you are expected to type it.

Ask it questions through any MCP-compatible AI assistant, or open the dashboard on
your phone. Both read the same corpus you collected, ranked the way you said.

---

## What it is

A self-hosted news aggregator with three faces:

| Face | What it's for |
|------|---------------|
| **MCP server** | Ask an AI assistant "what happened with X this week?" and get an answer grounded in *your* corpus, with citations. |
| **Dashboard** | A fast web + mobile view of what matters to you today. No infinite scroll, no engagement metrics. |
| **CLI** | Backfill, re-rank, inspect, export. Everything scriptable. |

## What makes it different

- **Your algorithm is a list of rules you wrote.** You edit it in the browser; it
  is stored as `config/profile.yaml`, which you can read, copy and keep under
  version control. Change it and the feed reorders immediately. Read it and you
  know exactly why an article surfaced — the dashboard shows the matched rules as
  chips on every item.
- **Runs without any AI at all.** No API key, no GPU, no model? It still collects,
  deduplicates, stores and keyword-searches everything, and ranks it against your
  profile. Add a model later and it enriches what it already collected. Nothing is
  lost by starting simple.
- **Four provider slots, two chains, automatic failover.** Two local/private and
  two cloud engines by default, for chat and embeddings. If one is down, the next
  in the chain takes over. Add more; the registry doesn't care.
- **Sources live in dated, versioned files.** Feeds die, move and get replaced.
  `config/sources/*.yaml` records when each was added, last verified, and whether
  it has been superseded — so a stale list is visible instead of silent.
- **Speaks your language, and adding one is a single file.** Every string lives
  in a flat JSON catalogue at `web/i18n/<lang>.json`. English and Portuguese ship
  complete; a new language is a copied file, translated, with no build step and
  no restart. Right-to-left is a one-line change. See
  [`docs/LOCALIZATION.md`](docs/LOCALIZATION.md).
- **Sharing sends the publisher's link, never yours.** Every article carries a
  Share control that opens your device's own share sheet, so it reaches every
  application you actually have installed. Browsers without one get a short list
  of plain share links instead. See *Sharing* below.
- **No third-party UI framework.** The dashboard is hand-written HTML, CSS and
  JavaScript served by our own API. No vendor banner, no telemetry, no analytics,
  no build step, and no Node anywhere in the container.

## Quick start

```bash
git clone https://github.com/RaymondJPayne/mcp-news
cd mcp-news
docker compose up -d
```

Open <http://localhost:8378>. A setup wizard asks you four things — your
language, where to keep your articles, which source bundles to read, and what you
are interested in — and then starts collecting. The first articles usually appear
within a minute or two.

Nothing above needs a file, an editor or a terminal beyond that one command.
There is no `.env` to copy and no example config to rename.

### Adding a model, later, if you want one

Entirely optional. With no model configured the application collects,
de-duplicates, stores, keyword-searches and ranks — see *Capability levels*
below. To add one, open **Settings → AI models** and point a slot at any
OpenAI-compatible endpoint, local or hosted. Keys are never stored in a
configuration file: the file names an environment variable, and you put the key
in `.env` or your shell environment.

```bash
LOCAL_CHAT_BASE_URL=http://host.docker.internal:1234/v1
LOCAL_EMBED_BASE_URL=http://host.docker.internal:1235/v1
# and/or
CLOUD_CHAT_API_KEY=sk-...
CLOUD_EMBED_API_KEY=sk-...
```

Then `docker compose exec node mcpnews enrich --backlog` processes everything you
already collected, highest interest score first.

## Your algorithm is a list of rules

You write these in the browser. This is what they look like on disk.

```yaml
interests:
  - name: Semiconductor policy
    match: [export control, fab, lithography, ASML, TSMC]
    weight: 5
  - name: AI governance
    match: [AI Act, model regulation, algorithmic accountability]
    weight: 4

places:
  - name: Brazil
    weight: 5
  - name: Ontario
    weight: 4

mute:
  domains: [example-clickbait.com]
  keywords: [horoscope]
```

No training, no feedback loop you cannot see, no drift. If it surfaces something
odd, the dashboard tells you which rule did it.

## Sharing

Every article in Today and in the article view has a Share control. What goes out
is the **publisher's own link** — never a link to this machine, never an address
only your network can resolve, and never an id from your database. An article we
collected without a source link shows no Share control at all.

Where the browser has the Web Share API — every current mobile browser and most
desktop ones — one tap opens the operating system's share sheet, which reaches
every application you have installed. That is the whole feature, and it is better
than any list we could write. Browsers without it get a short explicit list
instead: Mastodon, Bluesky, LinkedIn, Reddit, WhatsApp, Telegram, Facebook, X,
email, and Copy link. Each of those is a plain share-intent URL opened in a new
tab — no vendor SDK, no embedded widget, no remote script, no tracking pixel — and
the icons are inline SVG we drew ourselves. Nothing about a share is recorded.
Your Mastodon server is remembered by your browser alone; Settings shows it and
can forget it.

**Attribution.** A share carries one optional extra line crediting where the
article reached you. It is on by default and configurable in **Settings →
Sharing**: turn it off, change the wording, or point the link at your own page
instead of the repository. Turning it off turns it off — nothing here re-enables
it later. LinkedIn, Facebook and Reddit accept only a link and write their own
preview, so the credit line does not travel with those three; the Settings screen
says so.

## Capability levels

The application announces which level it is running at, in the header and in
`/api/status`, so a degraded mode is visible rather than silently worse.

| Level | Needs | You get |
|---|---|---|
| **0 — Collect** | nothing at all | Fetching, de-duplication, the archive, keyword search, profile ranking, the dashboard, the MCP keyword tools |
| **1 — Index** | an embedding model | The above, plus search by meaning and hybrid search |
| **2 — Understand** | embedding and chat | The above, plus cited answers through `ask` |

Level 0 is the floor the project guarantees, and it is a real product rather than
a placeholder.

## Connecting an AI assistant

```json
{
  "mcpServers": {
    "news": {
      "command": "docker",
      "args": ["compose", "exec", "-T", "node", "mcpnews", "mcp"]
    }
  }
}
```

Then ask: *"What changed on semiconductor export controls in the last fortnight?"*

See [`docs/MCP.md`](docs/MCP.md) for the full tool surface.

## Documentation

| Document | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Components, pipeline, storage, data flow |
| [`docs/PROVIDERS.md`](docs/PROVIDERS.md) | Provider slots, chains, failover, degraded operation |
| [`docs/SOURCES.md`](docs/SOURCES.md) | Source file format and lifecycle |
| [`docs/PROFILE.md`](docs/PROFILE.md) | Profile schema and scoring model |
| [`docs/MCP.md`](docs/MCP.md) | MCP tool reference |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phases and what "done" means |
| [`docs/LOCALIZATION.md`](docs/LOCALIZATION.md) | Adding a language, in one file |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Extension points and how to add one |

## Status

Collecting, ranking, the dashboard and the MCP server work end to end with no
model configured. Embeddings, chains and failover work when a provider is
configured. Translation, entity extraction and change detection do not exist yet
and say so where you would expect to find them.

[`docs/ROADMAP.md`](docs/ROADMAP.md) states each phase honestly, including what
is stubbed and why.

**This project ships no authentication and claims none.** It binds to
`127.0.0.1`. If you want it on a network, that is your reverse proxy's job.

## Licence

AGPL-3.0 for the code. Schemas and source lists are MIT, so anyone can build a
compatible client. See [`LICENSE`](LICENSE).
