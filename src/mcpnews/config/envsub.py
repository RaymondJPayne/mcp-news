"""``${VAR}`` and ``${VAR:-default}`` substitution for configuration values.

Used by providers.yaml and by source URLs for keyed endpoints. Secrets are never
written into a configuration file; the file names the variable and this resolves
it at load time.
"""
from __future__ import annotations

import os
import re
from typing import Any

_PATTERN = re.compile(r"\$\{(\w+)(?::-(.*?))?\}")


def substitute(value: Any, env: dict[str, str] | None = None) -> Any:
    src = os.environ if env is None else env
    if isinstance(value, str):
        def sub(m: re.Match[str]) -> str:
            name, default = m.group(1), m.group(2)
            got = src.get(name, "")
            return got if got else (default or "")
        return _PATTERN.sub(sub, value)
    if isinstance(value, dict):
        return {k: substitute(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, env) for v in value]
    return value


def referenced_vars(value: Any) -> set[str]:
    """Every environment variable a config tree mentions. Used by the status screen."""
    found: set[str] = set()
    if isinstance(value, str):
        found.update(m.group(1) for m in _PATTERN.finditer(value))
    elif isinstance(value, dict):
        for v in value.values():
            found |= referenced_vars(v)
    elif isinstance(value, list):
        for v in value:
            found |= referenced_vars(v)
    return found
