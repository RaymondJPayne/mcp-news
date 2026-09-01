"""The API the dashboard depends on, including the unbroken non-technical path."""
from __future__ import annotations

import json
import re
from pathlib import Path

EN = json.loads((Path(__file__).resolve().parents[1] / "web" / "i18n" / "en.json")
                .read_text(encoding="utf-8"))


def test_health_before_setup(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["configured"] is False
    assert body["tier"] == 0          # nothing configured means Tier 0, honestly


def test_reading_endpoints_are_gated_until_setup_is_done(client):
    for path in ("/api/foryou", "/api/search?q=x", "/api/sources"):
        r = client.get(path)
        assert r.status_code == 409
        assert r.json()["error"]["key"] == "err.setup.required"


def test_setup_options_offer_the_shipped_bundles_and_locales(client):
    options = client.get("/api/setup/options").json()
    assert {"core-world", "gov-agency", "tech-science"} <= {b["name"] for b in options["bundles"]}
    assert {"en", "pt"} <= {locale["code"] for locale in options["locales"]}


def test_path_check_reports_writability(client, tmp_path):
    ok = client.post("/api/setup/check-path", json={"path": str(tmp_path / "new")}).json()
    assert ok["ok"] is True and ok["message_key"] == ""


def _complete_setup(client, tmp_path):
    return client.post("/api/setup/complete", json={
        "language": "pt",
        "data_dir": str(tmp_path / "data"),
        "archive_dir": str(tmp_path / "archive"),
        "bundles": ["core-world"],
        "interests": [{"name": "Semiconductors",
                       "match": ["lithography", "export control"], "weight": 5}],
    })


def test_the_wizard_writes_real_configuration(client, sandbox):
    r = _complete_setup(client, sandbox)
    assert r.status_code == 200

    config = Path(sandbox) / "config"
    settings = (config / "settings.yaml").read_text()
    assert "configured: true" in settings
    assert "language: pt" in settings
    assert "lithography" in (config / "profile.yaml").read_text()
    assert (config / "providers.yaml").is_file()
    assert (config / "sources" / "local.yaml").is_file()

    status = client.get("/api/status").json()
    assert status["configured"] is True
    assert status["sources_active"] >= 4
    assert status["tier"] == 0
    assert client.get("/api/foryou").status_code == 200


def test_settings_round_trip(client, sandbox):
    _complete_setup(client, sandbox)
    r = client.put("/api/settings", json={
        "language": "en",
        "bundles": ["core-world", "tech-science"],
        "collection": {"interval_min": 30, "concurrency": 4, "respect_robots": False,
                       "fetch_fulltext": False},
    })
    assert r.status_code == 200
    got = client.get("/api/settings").json()
    assert got["language"] == "en"
    assert got["collection"]["interval_min"] == 30
    assert got["collection"]["respect_robots"] is False
    assert set(got["bundles"]) == {"core-world", "tech-science"}


def test_profile_round_trip_and_rescore(client, sandbox):
    _complete_setup(client, sandbox)
    profile = client.get("/api/profile").json()
    profile["interests"].append({"name": "Brazil", "match": ["Brasilia"], "weight": 4,
                                 "must_include": [], "exclude": [],
                                 "in_title_multiplier": 2})
    r = client.put("/api/profile", json=profile)
    assert r.status_code == 200 and "rescored" in r.json()
    assert any(i["name"] == "Brazil" for i in client.get("/api/profile").json()["interests"])


def test_an_invalid_profile_is_refused_with_a_translatable_key(client, sandbox):
    _complete_setup(client, sandbox)
    r = client.put("/api/profile", json={"interests": [
        {"name": "Bad", "match": ["x"], "weight": -5}]})
    assert r.status_code == 400
    assert r.json()["error"]["key"] == "err.profile.invalid"


def test_sources_can_be_disabled_from_the_api(client, sandbox):
    _complete_setup(client, sandbox)
    sources = client.get("/api/sources").json()["sources"]
    first = sources[0]["id"]
    assert client.patch(f"/api/sources/{first}", json={"status": "paused"}).status_code == 200
    after = {s["id"]: s["status"] for s in client.get("/api/sources").json()["sources"]}
    assert after[first] == "paused"


def test_adding_a_source_rejects_something_that_is_not_a_url(client, sandbox):
    _complete_setup(client, sandbox)
    r = client.post("/api/sources", json={"url": "not a url"})
    assert r.status_code == 400
    assert r.json()["error"]["key"] == "err.source.bad_url"


def test_every_error_key_the_api_can_emit_exists_in_the_catalogue():
    """No English ever reaches the browser, so every key must be translatable."""
    source = Path(__file__).resolve().parents[1] / "src" / "mcpnews"
    keys = set()
    for path in source.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        keys |= set(re.findall(
            r'"((?:err|settings|search|setup|share|status)\.[a-z0-9_.]+)"', text))
    # Filenames look like dot-paths and are not message keys.
    keys = {k for k in keys if not k.endswith((".yaml", ".json", ".py", ".md"))}
    missing = sorted(k for k in keys if k not in EN)
    assert not missing, f"these message keys are not in en.json: {missing}"


def test_the_dashboard_is_served_and_needs_no_build_step(client):
    for path in ("/", "/app.js", "/styles.css", "/i18n/en.json", "/i18n/pt.json",
                 "/manifest.webmanifest"):
        assert client.get(path).status_code == 200, path
    index = client.get("/").text
    assert "node_modules" not in index
    assert "<script src=\"/app.js\"" in index      # our own file, from our own origin


def test_validation_errors_are_translatable_too(client, sandbox):
    """FastAPI's own error prose is English. It must never reach the browser."""
    _complete_setup(client, sandbox)
    r = client.get("/api/foryou?hours=999999")
    assert r.status_code == 400
    body = r.json()
    assert set(body) == {"error"} and body["error"]["key"] in EN
    assert "Input should be" not in r.text


def test_unknown_paths_fall_through_to_the_dashboard_not_a_traceback(client):
    assert client.get("/some/deep/route").status_code == 200
    assert client.get("/api/nope").status_code == 404


def test_static_serving_refuses_path_traversal(client):
    r = client.get("/../pyproject.toml")
    assert r.status_code in (200, 404)
    assert "hatchling" not in r.text
