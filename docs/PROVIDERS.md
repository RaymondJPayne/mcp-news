# Providers, chains and failover

Two rules shape this whole subsystem:

1. **The application never talks to a vendor SDK.** It talks to `ChatProvider` and
   `EmbedProvider`. Everything else is an adapter behind those two interfaces.
2. **No model is ever required.** Every capability that needs one degrades to a
   defined, useful behaviour when none is reachable.

---

## 1. Slots

A *slot* is a named, configured engine. Four ship by default — two private, two
cloud — covering the two functions the system needs.

| Slot | Function | Typical engine |
|---|---|---|
| `local_chat` | chat / completion | llama.cpp, Ollama, LM Studio, vLLM |
| `local_embed` | embeddings | llama.cpp `--embeddings`, Infinity, TEI |
| `cloud_chat` | chat / completion | OpenAI, Anthropic, Mistral, Groq, OpenRouter |
| `cloud_embed` | embeddings | OpenAI, Voyage, Cohere, Jina |

Four is the floor, not the ceiling. `providers:` is a map — add
`work_chat`, `backup_embed`, or a fifth and sixth of anything, and reference them
in a chain. Nothing in the code counts slots.

## 2. Configuration

`config/providers.yaml`. Secrets are never written here — only the *name* of the
environment variable that holds them.

```yaml
providers:
  local_chat:
    kind: openai_compatible      # adapter id from the registry
    base_url: ${LOCAL_CHAT_BASE_URL}
    model: ${LOCAL_CHAT_MODEL:-qwen3-8b-instruct}
    api_key_env: LOCAL_CHAT_API_KEY   # optional; many local servers need none
    timeout_s: 30
    max_tokens: 1024
    # Reasoning models emit chain-of-thought that is billed to your decode budget
    # and then discarded. Off by default; turn it on deliberately.
    reasoning: off

  local_embed:
    kind: openai_compatible
    base_url: ${LOCAL_EMBED_BASE_URL}
    model: ${LOCAL_EMBED_MODEL:-bge-m3}
    dimensions: 1024
    batch_size: 32
    timeout_s: 20

  cloud_chat:
    kind: openai_compatible
    base_url: https://api.openai.com/v1
    model: ${CLOUD_CHAT_MODEL:-gpt-4o-mini}
    api_key_env: CLOUD_CHAT_API_KEY
    timeout_s: 45
    max_tokens: 1024
    cost_per_1k_in: 0.00015       # optional, enables the spend report
    cost_per_1k_out: 0.0006

  cloud_embed:
    kind: openai_compatible
    base_url: https://api.openai.com/v1
    model: ${CLOUD_EMBED_MODEL:-text-embedding-3-small}
    api_key_env: CLOUD_EMBED_API_KEY
    dimensions: 1536
    batch_size: 128

chains:
  # Order is preference. First healthy slot wins.
  chat:  [local_chat, cloud_chat]
  embed: [local_embed, cloud_embed]

failover:
  max_attempts_per_slot: 2
  backoff_initial_s: 1.0
  backoff_factor: 2.0
  open_after_failures: 3      # consecutive failures before the breaker opens
  cooldown_s: 300             # how long an open breaker stays open
  probe_interval_s: 60        # background health check
  # Cost guard: never silently spend money because a local box rebooted.
  require_confirmation_for_paid_failover: false
```

**Privacy-first ordering.** The default chains put local before cloud, so the
private engine is tried first and the cloud is a safety net. Reverse it if you
prefer quality over locality — the code has no opinion, only the file does.

## 3. Failover behaviour

Each slot carries a circuit breaker.

```
       ┌──────── success ────────┐
       ▼                         │
   ┌────────┐  n failures   ┌────────┐  cooldown  ┌───────────┐
   │ CLOSED │ ────────────► │  OPEN  │ ─────────► │ HALF-OPEN │
   └────────┘               └────────┘            └───────────┘
       ▲                                                │
       └──────────── probe succeeds ────────────────────┘
```

A request walks the chain:

1. Skip any slot whose breaker is `OPEN`.
2. Try the slot, up to `max_attempts_per_slot`, with exponential backoff.
3. On success, reset that slot's failure count and return.
4. On exhaustion, record the failure, maybe open the breaker, move to the next slot.
5. If every slot in the chain is exhausted, raise `NoProviderAvailable` — which
   callers treat as "degrade", never as "crash".

**What counts as a failure** matters. Connection errors, timeouts, 5xx and 429 are
failures and trip the breaker. A 400 from a malformed request is *not* — that is
our bug, and failing over would just repeat it against a second provider and
double the cost. The classification lives in `providers/errors.py` so adapters
share one definition.

**Embeddings have an extra constraint.** Vectors from different models are not
comparable. Each stored vector records `model_id` and `dimensions`; the store
refuses to mix them in one index. Failing over from `local_embed` to
`cloud_embed` mid-corpus therefore does **not** silently produce a broken index —
it writes into a second vector space, and search queries whichever space the query
embedding belongs to. `mcpnews reindex --to cloud_embed` consolidates when you
choose to. Chat has no such constraint and fails over freely.

## 4. Degraded operation

The system defines three capability tiers and announces which one it is in, on
startup, in `/api/health`, and in the dashboard header.

| Tier | Requires | You get | You don't get |
|---|---|---|---|
| **0 — Collect** | nothing | Fetch, extract, dedupe, store, full-text keyword search, profile ranking, dashboard, MCP keyword tools | Semantic search, translation, summaries, entities |
| **1 — Index** | an embed provider | Everything above, plus semantic and hybrid search, near-duplicate clustering, "more like this" | Translation, summaries, entities |
| **2 — Understand** | embed + chat | Everything above, plus translation, per-article context, entity and relationship extraction, `ask` | — |

Two consequences worth stating plainly.

**Tier 0 is genuinely useful, not a stub.** Rule-based profile scoring needs no
model at all — it is string matching with weights. A reader with no GPU and no API
key still gets a curated, de-duplicated, searchable, personally-ranked feed. That
is the floor the project guarantees.

**Nothing collected in a lower tier is wasted.** Every article carries an
`enrichment_state` per capability:

```
embedded:    pending | done | failed | skipped
translated:  pending | done | failed | skipped | not_needed
contextual:  pending | done | failed | skipped
entities:    pending | done | failed | skipped
```

Configure a provider a month later and `mcpnews enrich --backlog` processes the
accumulated corpus in relevance order, highest first. Collect now, understand
later — that is the intended workflow, not a fallback.

## 5. Adding a provider adapter

Adapters are ~60 lines. Register and go.

```python
from mcpnews.providers.base import ChatProvider, register

@register("my_engine")
class MyEngine(ChatProvider):
    def __init__(self, cfg): ...

    async def chat(self, messages, *, schema=None, max_tokens=None) -> str:
        """Return the assistant message text.

        Raise ProviderUnavailable for anything the caller should fail over on;
        raise ProviderRequestError for our own bad requests, which must not
        trip the breaker.
        """

    async def health(self) -> bool:
        """Cheap liveness probe. Must not cost money."""
```

`kind: my_engine` in `providers.yaml` is now valid. The registry resolves by
name at load time, and an unknown `kind` is a startup error with the list of
registered adapters — not a stack trace at first use.

Ship it with a contract test: `tests/providers/test_contract.py` runs the same
suite against every registered adapter.
