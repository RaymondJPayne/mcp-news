# mcp-news

**News for the reader — not news that turns the reader into the product.**

Your news feed is currently chosen by someone whose income depends on how long you
keep scrolling. `mcp-news` inverts that. You write your interests into a file you
can read. That file *is* the ranking algorithm. Nothing about you is transmitted
anywhere, because there is nowhere to transmit it to — the whole thing runs on
your own machine.

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

- **Your algorithm is a text file.** `profile.yaml` says what you care about and
  where. Edit it, and the ranking changes. Read it, and you know exactly why an
  article surfaced — the dashboard shows the matched rules on every item.
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
- **No third-party UI framework.** The dashboard is hand-written HTML, CSS and
  JavaScript served by our own API. No vendor banner, no telemetry, no analytics,
  no build step.

## Quick start

```bash
git clone https://github.com/RaymondJPayne/mcp-news
cd mcp-news
cp .env.example .env
cp config/profile.example.yaml config/profile.yaml
docker compose up -d
```

Dashboard on <http://localhost:8378>. It starts collecting immediately — with no
model configured, in keyword mode.

To add intelligence, point `.env` at any OpenAI-compatible endpoint:

```bash
LOCAL_CHAT_BASE_URL=http://host.docker.internal:1234/v1
LOCAL_EMBED_BASE_URL=http://host.docker.internal:1235/v1
# and/or
CLOUD_CHAT_API_KEY=sk-...
CLOUD_EMBED_API_KEY=sk-...
```

Then `docker compose exec node mcpnews enrich --backlog` to process what you
already have.

## Your algorithm is a file

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
odd, the dashboard tells you which line did it.

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
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Extension points and how to add one |

## Status

**Phase 0 — scaffold.** Interfaces and structure are defined; implementations are
being filled in. See [`docs/ROADMAP.md`](docs/ROADMAP.md) for what works today.

## Licence

AGPL-3.0 for the code. Schemas and source lists are MIT, so anyone can build a
compatible client. See [`LICENSE`](LICENSE).
