"""Loading and saving ``config/providers.yaml``.

Secrets are never written here. The file names the environment variable that
holds a key; this module resolves ``${VAR}`` and ``${VAR:-default}`` at load
time and hands the adapter a plain dictionary.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from mcpnews import paths
from mcpnews.config.envsub import substitute
from mcpnews.config.yamlio import read_yaml, write_yaml

PROVIDERS_FILENAME = "providers.yaml"

_HEADER = """\
# Provider slots, chains and failover.
#
# Secrets never appear in this file. api_key_env names the environment variable
# that holds the key; put the key itself in .env or your shell environment.
#
# Edited from the Settings screen. See docs/PROVIDERS.md.
"""

#: Four slots ship by default — two private, two cloud — but nothing counts
#: slots. Add work_chat, backup_embed or a sixth of anything and reference it in
#: a chain.
DEFAULT_CONFIG: dict[str, Any] = {
    "providers": {
        "local_chat": {
            "kind": "openai_compatible", "function": "chat",
            "base_url": "${LOCAL_CHAT_BASE_URL}",
            "model": "${LOCAL_CHAT_MODEL:-qwen3-8b-instruct}",
            "api_key_env": "LOCAL_CHAT_API_KEY",
            "timeout_s": 30, "max_tokens": 1024, "reasoning": "off",
        },
        "local_embed": {
            "kind": "openai_compatible", "function": "embed",
            "base_url": "${LOCAL_EMBED_BASE_URL}",
            "model": "${LOCAL_EMBED_MODEL:-bge-m3}",
            "api_key_env": "LOCAL_EMBED_API_KEY",
            "dimensions": 1024, "batch_size": 32, "timeout_s": 20,
        },
        "cloud_chat": {
            "kind": "openai_compatible", "function": "chat",
            "base_url": "${CLOUD_CHAT_BASE_URL:-https://api.openai.com/v1}",
            "model": "${CLOUD_CHAT_MODEL:-gpt-4o-mini}",
            "api_key_env": "CLOUD_CHAT_API_KEY", "requires_api_key": True,
            "timeout_s": 45, "max_tokens": 1024,
            "cost_per_1k_in": 0.00015, "cost_per_1k_out": 0.0006,
        },
        "cloud_embed": {
            "kind": "openai_compatible", "function": "embed",
            "base_url": "${CLOUD_EMBED_BASE_URL:-https://api.openai.com/v1}",
            "model": "${CLOUD_EMBED_MODEL:-text-embedding-3-small}",
            "api_key_env": "CLOUD_EMBED_API_KEY", "requires_api_key": True,
            "dimensions": 1536, "batch_size": 128,
        },
    },
    # Order is preference. Local first keeps reading private and costs nothing.
    "chains": {"chat": ["local_chat", "cloud_chat"], "embed": ["local_embed", "cloud_embed"]},
    "failover": {
        "max_attempts_per_slot": 2, "backoff_initial_s": 1.0, "backoff_factor": 2.0,
        "open_after_failures": 3, "cooldown_s": 300, "probe_interval_s": 60,
        "require_confirmation_for_paid_failover": False,
    },
}

#: Slots whose function the file does not state are inferred from their name.
_EMBED_HINTS = ("embed", "embedding", "vector")


def providers_path() -> Path:
    return paths.config_dir() / PROVIDERS_FILENAME


def slot_is_usable(cfg: dict) -> bool:
    """Enough configuration to be worth trying.

    A cloud slot ships with a working base_url and a default model, so those two
    alone would report "configured" on a completely fresh install and the status
    line would claim a capability tier the reader does not have. A slot that
    states ``requires_api_key`` is usable only once its key is actually present
    in the environment.
    """
    import os

    if not (cfg.get("base_url") and cfg.get("model")):
        return False
    if cfg.get("requires_api_key"):
        key_env = cfg.get("api_key_env")
        return bool(key_env and os.environ.get(str(key_env), "").strip())
    return True


def infer_function(slot: str, cfg: dict) -> str:
    stated = str(cfg.get("function") or "").lower()
    if stated in ("chat", "embed"):
        return stated
    return "embed" if any(h in slot.lower() for h in _EMBED_HINTS) else "chat"


def load_raw() -> dict:
    """The file as written, with ``${VAR}`` intact. What the Settings screen edits."""
    raw = read_yaml(providers_path(), default=None)
    if not isinstance(raw, dict):
        return {k: (dict(v) if isinstance(v, dict) else list(v))
                for k, v in DEFAULT_CONFIG.items()}
    for key, default in DEFAULT_CONFIG.items():
        raw.setdefault(key, default)
    return raw


def load_resolved() -> dict:
    """The file with environment variables substituted. What adapters receive."""
    return substitute(load_raw())


def save(raw: dict) -> None:
    write_yaml(providers_path(), raw, header=_HEADER)


def ensure_file() -> None:
    if not providers_path().is_file():
        save({k: (dict(v) if isinstance(v, dict) else list(v))
              for k, v in DEFAULT_CONFIG.items()})


def redacted(raw: dict | None = None) -> dict:
    """What the Settings screen may show. No key ever reaches the browser."""
    import os

    raw = raw or load_raw()
    out = {"providers": {}, "chains": raw.get("chains", {}), "failover": raw.get("failover", {})}
    resolved = substitute(raw).get("providers", {})
    for slot, cfg in (raw.get("providers") or {}).items():
        res = resolved.get(slot, {})
        key_env = cfg.get("api_key_env")
        out["providers"][slot] = {
            "kind": cfg.get("kind", "openai_compatible"),
            "function": infer_function(slot, cfg),
            "base_url": cfg.get("base_url", ""),
            "resolved_base_url": res.get("base_url", ""),
            "model": cfg.get("model", ""),
            "resolved_model": res.get("model", ""),
            "api_key_env": key_env or "",
            "api_key_present": bool(key_env and os.environ.get(str(key_env), "").strip()),
            "dimensions": cfg.get("dimensions"),
            "batch_size": cfg.get("batch_size"),
            "timeout_s": cfg.get("timeout_s"),
            "max_tokens": cfg.get("max_tokens"),
            "reasoning": cfg.get("reasoning", "off"),
            "requires_api_key": bool(cfg.get("requires_api_key")),
            "configured": slot_is_usable(res),
        }
    return out
