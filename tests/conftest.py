"""Shared fixtures.

Every test runs against a temporary configuration and data directory, so a test
run never reads or writes the developer's own corpus, and no test needs a
network, an API key or a GPU.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """An isolated installation: its own config, data and archive directories."""
    config = tmp_path / "config"
    (config / "sources").mkdir(parents=True)
    for name in ("_schema.json",):
        shutil.copy(REPO / "config" / "sources" / name, config / "sources" / name)
    for yaml_file in (REPO / "config" / "sources").glob("*.yaml"):
        shutil.copy(yaml_file, config / "sources" / yaml_file.name)

    monkeypatch.setenv("MCPNEWS_CONFIG_DIR", str(config))
    monkeypatch.setenv("MCPNEWS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MCPNEWS_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("MCPNEWS_WEB_DIR", str(REPO / "web"))
    # No provider is configured in tests: Tier 0 is what we are checking.
    for var in ("LOCAL_CHAT_BASE_URL", "LOCAL_EMBED_BASE_URL",
                "CLOUD_CHAT_API_KEY", "CLOUD_EMBED_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


@pytest.fixture()
def store(sandbox):
    from mcpnews.config.settings import load as load_settings
    from mcpnews.store.registry import open_store

    s = open_store(load_settings())
    yield s
    s.close()


@pytest.fixture()
def client(sandbox):
    from fastapi.testclient import TestClient

    from mcpnews.api.app import create_app

    with TestClient(create_app(collector_loop=False)) as c:
        yield c
