"""The JSON API the dashboard consumes.

Two properties are load-bearing and easy to lose:

* **No English in a response.** Errors and notes are catalogue keys with
  parameters. The browser renders them in the reader's language.
* **Everything configurable is configurable here.** The wizard and the settings
  screens write real files through these endpoints; there is no happy path that
  requires a text editor or an environment variable.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from mcpnews import __version__, paths
from mcpnews.api.errors import ApiError, bad_request, not_found, setup_required
from mcpnews.config import profile as profile_cfg
from mcpnews.config import providers as providers_cfg
from mcpnews.config import settings as settings_cfg
from mcpnews.i18n import available_locales
from mcpnews.ingest.canonical import canonicalise, domain_of, is_probably_url
from mcpnews.ingest.fetcher import FetchError, Fetcher
from mcpnews.ingest.pipeline import Collector, rescore
from mcpnews.rank.scorer import CompiledProfile
from mcpnews.runtime import App, ensure_config_files
from mcpnews.search.service import search as run_search
from mcpnews.search.views import display_score
from mcpnews.sources import loader
from mcpnews.sources.registry import adapter_for, registered as registered_kinds, sniff_kind
from mcpnews.store.base import SourceRecord

log = logging.getLogger("mcpnews.api")

STATIC_SUFFIXES = {".html", ".css", ".js", ".json", ".webmanifest", ".svg", ".png", ".ico"}


# --- request bodies ---------------------------------------------------------
class InterestIn(BaseModel):
    name: str
    match: list[str] = Field(default_factory=list)
    must_include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    weight: float = 3.0
    in_title_multiplier: float | None = None


class SetupIn(BaseModel):
    language: str = "en"
    data_dir: str = ""
    archive_dir: str = ""
    bundles: list[str] = Field(default_factory=list)
    interests: list[InterestIn] = Field(default_factory=list)
    places: list[InterestIn] = Field(default_factory=list)


class PathIn(BaseModel):
    path: str


class SettingsIn(BaseModel):
    language: str | None = None
    data_dir: str | None = None
    archive_dir: str | None = None
    bundles: list[str] | None = None
    collection: dict[str, Any] | None = None


class ProfileIn(BaseModel):
    identity: list[InterestIn] = Field(default_factory=list)
    interests: list[InterestIn] = Field(default_factory=list)
    places: list[InterestIn] = Field(default_factory=list)
    organisations: list[InterestIn] = Field(default_factory=list)
    mute_domains: list[str] = Field(default_factory=list)
    mute_keywords: list[str] = Field(default_factory=list)
    source_boost: dict[str, float] = Field(default_factory=dict)
    source_penalty: dict[str, float] = Field(default_factory=dict)
    min_score: float = 1.0
    cap_per_rule: float = 16.0
    default_half_life_h: float = 36.0


class SourceIn(BaseModel):
    url: str
    name: str = ""
    kind: str = "auto"
    lang: str = "en"
    region: str = "global"
    topics: list[str] = Field(default_factory=list)
    interval_min: int = 60


class SourcePatch(BaseModel):
    status: str | None = None
    name: str | None = None
    interval_min: int | None = None
    lang: str | None = None
    region: str | None = None
    topics: list[str] | None = None


class ProvidersIn(BaseModel):
    providers: dict[str, dict[str, Any]]
    chains: dict[str, list[str]]
    failover: dict[str, Any] = Field(default_factory=dict)


class SlotIn(BaseModel):
    slot: str


# --- helpers ----------------------------------------------------------------
def _profile_from(body: ProfileIn) -> dict:
    def rules(items: list[InterestIn]) -> list[dict]:
        out = []
        for r in items:
            if not r.name.strip():
                continue
            d: dict[str, Any] = {"name": r.name.strip(), "match": r.match,
                                 "weight": r.weight}
            if r.must_include:
                d["must_include"] = r.must_include
            if r.exclude:
                d["exclude"] = r.exclude
            if r.in_title_multiplier is not None:
                d["in_title_multiplier"] = r.in_title_multiplier
            out.append(d)
        return out

    return {
        "version": 1,
        "identity": rules(body.identity),
        "interests": rules(body.interests),
        "places": rules(body.places),
        "organisations": rules(body.organisations),
        "sources": {"boost": body.source_boost, "penalty": body.source_penalty},
        "mute": {"domains": body.mute_domains, "keywords": body.mute_keywords},
        "scoring": {"min_score": body.min_score, "cap_per_rule": body.cap_per_rule,
                    "default_half_life_h": body.default_half_life_h},
    }


def _profile_out(p) -> dict:
    def rules(items) -> list[dict]:
        return [{"name": r.name, "match": r.match, "must_include": r.must_include,
                 "exclude": r.exclude, "weight": r.weight,
                 "in_title_multiplier": r.in_title_multiplier} for r in items]

    return {
        "identity": rules(p.identity), "interests": rules(p.interests),
        "places": rules(p.places), "organisations": rules(p.organisations),
        "mute_domains": p.mute_domains, "mute_keywords": p.mute_keywords,
        "source_boost": p.source_boost, "source_penalty": p.source_penalty,
        "min_score": p.scoring.min_score, "cap_per_rule": p.scoring.cap_per_rule,
        "default_half_life_h": p.scoring.default_half_life_h,
        "path": str(profile_cfg.profile_path()),
    }


def _in_container() -> bool:
    """Best-effort. Only used to show a more helpful sentence about bind mounts."""
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


def _feed_items(app: App, articles, half_life_h) -> list[dict]:
    out = []
    for a in articles:
        d = a.to_dict()
        d["display_score"] = round(
            display_score(a.interest_score, a.published_at or a.fetched_at, half_life_h), 3)
        out.append(d)
    return out


# --- application ------------------------------------------------------------
def create_app(*, collector_loop: bool = True) -> FastAPI:
    ensure_config_files()
    api = FastAPI(title="mcp-news", version=__version__, docs_url=None, redoc_url=None)
    state: dict[str, Any] = {"collecting": False, "last_report": None}
    app_ctx = App.create()
    api.state.app = app_ctx
    api.state.runtime = state

    def ctx() -> App:
        return api.state.app

    def require_configured() -> App:
        app = ctx()
        if not app.configured:
            raise setup_required()
        return app

    # ---- background loops ------------------------------------------------
    async def collect_once(source_ids: list[str] | None = None) -> dict:
        app = ctx()
        if state["collecting"]:
            raise ApiError(409, "err.busy")
        state["collecting"] = True
        try:
            collector = Collector(app.settings, app.store, app.archive, app.profile)
            report = await collector.run_once(source_ids=source_ids)
            state["last_report"] = report.to_dict()
            return state["last_report"]
        finally:
            state["collecting"] = False

    async def loop() -> None:
        # A first pass shortly after start, then on the configured interval.
        await asyncio.sleep(5)
        while True:
            app = ctx()
            try:
                if app.configured:
                    if not state["collecting"]:
                        await collect_once()
                    await app.providers.probe_all()
                    if app.providers.has_embed():
                        from mcpnews.enrich import run_embeddings
                        await run_embeddings(app.store, app.providers, limit=200)
            except Exception as exc:  # noqa: BLE001 - a loop that dies stops the product
                log.warning("collection loop: %s", exc)
            await asyncio.sleep(max(60, ctx().settings.collection.interval_min * 60))

    @api.on_event("startup")
    async def _startup() -> None:  # pragma: no cover - exercised by running the server
        if collector_loop:
            api.state.loop_task = asyncio.create_task(loop())

    @api.on_event("shutdown")
    async def _shutdown() -> None:  # pragma: no cover
        task = getattr(api.state, "loop_task", None)
        if task:
            task.cancel()
        ctx().close()

    @api.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    # ================= health, status, locales =============================
    @api.get("/api/health")
    async def health() -> dict:
        app = ctx()
        return {"ok": True, "tier": app.tier(), "configured": app.configured,
                "version": __version__}

    @api.get("/api/status")
    async def status() -> dict:
        app = ctx()
        data = app.status()
        data["collecting"] = state["collecting"]
        data["last_report"] = state["last_report"]
        data["bundle_errors"] = loader.bundle_errors()
        return data

    @api.get("/api/locales")
    async def locales() -> dict:
        return {"locales": available_locales(), "language": ctx().settings.language}

    # ================= setup wizard ========================================
    @api.get("/api/setup/state")
    async def setup_state() -> dict:
        app = ctx()
        defaults = settings_cfg.defaults()
        return {
            "configured": app.configured,
            "language": app.settings.language,
            "in_container": _in_container(),
            "defaults": {"data_dir": defaults.data_dir, "archive_dir": defaults.archive_dir},
            "version": __version__,
        }

    @api.get("/api/setup/options")
    async def setup_options() -> dict:
        bundles = [b.to_dict() for b in loader.load_bundles()]
        return {
            "locales": available_locales(),
            "bundles": bundles,
            "starters": sorted(profile_cfg.STARTERS),
            "source_kinds": registered_kinds(),
        }

    @api.post("/api/setup/check-path")
    async def check_path(body: PathIn) -> dict:
        target = Path(body.path).expanduser() if body.path.strip() else None
        if target is None:
            raise bad_request("err.path.cannot_create")
        ok, key = paths.is_writable(target)
        free = None
        if ok:
            try:
                free = shutil.disk_usage(target).free
            except OSError:
                free = None
        return {"ok": ok, "message_key": key, "free_bytes": free, "path": str(target)}

    @api.post("/api/setup/complete")
    async def setup_complete(body: SetupIn) -> dict:
        app = ctx()
        settings = settings_cfg.load()
        settings.language = body.language or "en"
        if body.data_dir.strip():
            settings.data_dir = str(Path(body.data_dir).expanduser())
        if body.archive_dir.strip():
            settings.archive_dir = str(Path(body.archive_dir).expanduser())
        settings.bundles = list(body.bundles)

        for target in (settings.data_path, settings.archive_path):
            ok, key = paths.is_writable(target)
            if not ok:
                raise bad_request(key, path=str(target))

        profile_body = ProfileIn(interests=body.interests, places=body.places)
        try:
            profile = profile_cfg.from_dict(_profile_from(profile_body))
        except profile_cfg.ProfileError as exc:
            raise bad_request("err.profile.invalid", detail=exc.detail) from None
        profile_cfg.save(profile)

        settings.configured = True
        settings_cfg.save(settings)
        providers_cfg.ensure_file()
        loader.ensure_local_bundle()

        # Rebuild against the chosen storage location before registering sources.
        app.close()
        api.state.app = App.create()
        registered = api.state.app.register_sources()

        asyncio.get_running_loop().create_task(_kick_off())
        return {"ok": True, "sources": registered, "tier": api.state.app.tier()}

    async def _kick_off() -> None:
        await asyncio.sleep(0.5)
        try:
            await collect_once()
        except Exception as exc:  # noqa: BLE001
            log.warning("first collection: %s", exc)

    @api.post("/api/setup/reset")
    async def setup_reset() -> dict:
        settings = settings_cfg.load()
        settings.configured = False
        settings_cfg.save(settings)
        ctx().reload_settings()
        return {"ok": True}

    # ================= settings ============================================
    @api.get("/api/settings")
    async def get_settings() -> dict:
        app = ctx()
        s = app.settings
        blob = app.archive.storage.describe()
        usage = None
        try:
            usage = app.archive.storage.usage().bytes
        except Exception:  # noqa: BLE001
            usage = None
        db = s.db_path
        return {
            "language": s.language,
            "data_dir": s.data_dir, "archive_dir": s.archive_dir,
            "bundles": s.bundles,
            "available_bundles": [b.to_dict() for b in loader.load_bundles()],
            "collection": {
                "interval_min": s.collection.interval_min,
                "concurrency": s.collection.concurrency,
                "per_host_delay_s": s.collection.per_host_delay_s,
                "respect_robots": s.collection.respect_robots,
                "fetch_fulltext": s.collection.fetch_fulltext,
            },
            "store": {"backend": s.store.backend},
            "blob": {"backend": s.blob.backend, **blob, "usage_bytes": usage},
            "database": {"path": str(db),
                         "size_bytes": db.stat().st_size if db.is_file() else 0},
            "config_dir": str(paths.config_dir()),
            "version": __version__,
            "locales": available_locales(),
        }

    @api.put("/api/settings")
    async def put_settings(body: SettingsIn) -> dict:
        app = ctx()
        s = settings_cfg.load()
        rebuild = False
        if body.language:
            s.language = body.language
        if body.data_dir is not None and body.data_dir.strip():
            new = str(Path(body.data_dir).expanduser())
            rebuild = rebuild or new != s.data_dir
            s.data_dir = new
        if body.archive_dir is not None and body.archive_dir.strip():
            new = str(Path(body.archive_dir).expanduser())
            rebuild = rebuild or new != s.archive_dir
            s.archive_dir = new
        if body.bundles is not None:
            s.bundles = list(body.bundles)
        if body.collection:
            c = body.collection
            s.collection.interval_min = int(c.get("interval_min", s.collection.interval_min))
            s.collection.concurrency = max(1, int(c.get("concurrency",
                                                       s.collection.concurrency)))
            s.collection.per_host_delay_s = float(c.get("per_host_delay_s",
                                                        s.collection.per_host_delay_s))
            s.collection.respect_robots = bool(c.get("respect_robots",
                                                     s.collection.respect_robots))
            s.collection.fetch_fulltext = bool(c.get("fetch_fulltext",
                                                     s.collection.fetch_fulltext))
        for target in (s.data_path, s.archive_path):
            ok, key = paths.is_writable(target)
            if not ok:
                raise bad_request(key, path=str(target))
        settings_cfg.save(s)

        if rebuild:
            app.close()
            api.state.app = App.create()
        else:
            app.reload_settings()
        api.state.app.register_sources()
        return {"ok": True, "restart_recommended": rebuild}

    # ================= providers ===========================================
    @api.get("/api/providers")
    async def get_providers() -> dict:
        from mcpnews.providers.registry import registered_kinds as kinds
        app = ctx()
        return {**providers_cfg.redacted(), "tier": app.tier(),
                "health": app.providers.health(), "kinds": kinds()}

    @api.put("/api/providers")
    async def put_providers(body: ProvidersIn) -> dict:
        raw = providers_cfg.load_raw()
        for slot, cfg in body.providers.items():
            existing = dict(raw.get("providers", {}).get(slot) or {})
            # Never accept a literal key from the browser: the file names an
            # environment variable and that is the only shape allowed.
            cfg.pop("api_key", None)
            existing.update({k: v for k, v in cfg.items()
                             if k not in ("resolved_base_url", "resolved_model",
                                          "api_key_present", "configured")})
            raw.setdefault("providers", {})[slot] = existing
        raw["chains"] = {k: list(v) for k, v in body.chains.items()}
        if body.failover:
            raw["failover"] = {**raw.get("failover", {}), **body.failover}
        providers_cfg.save(raw)
        ctx().reload_providers()
        return {"ok": True, "tier": ctx().tier()}

    @api.post("/api/providers/test")
    async def test_provider(body: SlotIn) -> dict:
        ok = await ctx().providers.test_slot(body.slot)
        return {"ok": ok, "slot": body.slot,
                "message_key": "settings.providers.test.ok" if ok
                else "settings.providers.test.failed"}

    # ================= profile =============================================
    @api.get("/api/profile")
    async def get_profile() -> dict:
        return _profile_out(ctx().profile)

    @api.put("/api/profile")
    async def put_profile(body: ProfileIn) -> dict:
        try:
            profile = profile_cfg.from_dict(_profile_from(body))
        except profile_cfg.ProfileError as exc:
            raise bad_request("err.profile.invalid", detail=exc.detail) from None
        profile_cfg.save(profile)
        app = ctx()
        app.reload_profile()
        changed = rescore(app.store, app.profile)
        return {"ok": True, "rescored": changed}

    @api.post("/api/profile/preview")
    async def preview_profile(body: ProfileIn, hours: int = Query(72, ge=1, le=8760),
                              limit: int = Query(20, ge=1, le=100)) -> dict:
        """Score the recent corpus against unsaved edits. Writes nothing."""
        app = require_configured()
        try:
            profile = profile_cfg.from_dict(_profile_from(body))
        except profile_cfg.ProfileError as exc:
            raise bad_request("err.profile.invalid", detail=exc.detail) from None
        compiled = CompiledProfile(profile)
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        scored = []
        for article in app.store.iter_articles():
            when = article.published_at or article.fetched_at or ""
            if when < since:
                continue
            score = compiled.score(article.title, article.body or article.summary,
                                   article.domain, {"summary": article.summary})
            if score.total < profile.scoring.min_score:
                continue
            scored.append({
                "article_id": article.id, "title": article.title, "url": article.url,
                "domain": article.domain, "published_at": article.published_at,
                "interest_score": round(score.total, 3),
                "matched_rules": [r.to_dict() for r in score.rules],
                "display_score": round(display_score(
                    score.total, when, profile.scoring.default_half_life_h), 3),
            })
        scored.sort(key=lambda d: d["display_score"], reverse=True)
        return {"items": scored[:limit], "threshold": profile.scoring.min_score}

    # ================= reading =============================================
    @api.get("/api/foryou")
    async def foryou(hours: int = Query(72, ge=1, le=8760),
                     limit: int = Query(30, ge=1, le=200),
                     half_life_h: float | None = Query(None, ge=0)) -> dict:
        app = require_configured()
        hl = app.profile.scoring.default_half_life_h if half_life_h is None else half_life_h
        articles = app.store.feed(hours=hours, limit=limit,
                                  min_score=app.profile.scoring.min_score, half_life_h=hl)
        return {"items": _feed_items(app, articles, hl),
                "threshold": app.profile.scoring.min_score,
                "half_life_h": hl, "tier": app.tier(),
                "collecting": state["collecting"],
                "total_articles": app.store.counts()["articles"]}

    @api.get("/api/search")
    async def search(q: str = Query(""), limit: int = Query(20, ge=1, le=100),
                     days: int | None = Query(90, ge=0),
                     lang: str | None = None, mode: str = "auto") -> dict:
        app = require_configured()
        result = await run_search(app, q, limit=limit, days=days or None, lang=lang, mode=mode)
        return {"results": [h.to_dict() for h in result.hits], "mode": result.mode,
                "count": len(result.hits), "note_key": result.note_key}

    @api.get("/api/article/{article_id}")
    async def article(article_id: int, include_body: bool = True) -> dict:
        app = require_configured()
        record = app.store.get_article(article_id)
        if record is None:
            raise not_found()
        data = record.to_dict(include_body=include_body)
        data["body_source"] = "live"
        if include_body and not record.body and record.archive_ref:
            archived = app.archive.read(record.archive_ref)
            if archived:
                data["body"] = archived.get("body", "")
                data["body_source"] = "archive"
        source = app.store.get_source(record.source_id) if record.source_id else None
        data["source"] = source.to_dict() if source else None
        return data

    @api.get("/api/explain/{article_id}")
    async def explain(article_id: int) -> dict:
        app = require_configured()
        record = app.store.get_article(article_id)
        if record is None:
            raise not_found()
        score = app.scorer.score(record.title, record.body or record.summary,
                                 record.domain, {"summary": record.summary})
        return {"article_id": article_id, "title": record.title,
                "total": round(score.total, 3), "stored": record.interest_score,
                "rules": [r.to_dict() for r in score.rules],
                "muted": score.muted, "muted_by": score.muted_by}

    @api.get("/api/timeline")
    async def timeline(term: str, days: int = Query(90, ge=1, le=3650),
                       bucket: str = "day") -> dict:
        app = require_configured()
        points = app.store.timeline(term, days=days, bucket=bucket)
        return {"term": term, "points": [{"t": t, "count": n} for t, n in points]}

    # ================= sources =============================================
    @api.get("/api/sources")
    async def sources() -> dict:
        app = require_configured()
        report = loader.check(app.store)
        report["kinds"] = registered_kinds()
        report["bundles"] = [b.to_dict() for b in loader.load_bundles()]
        return report

    @api.post("/api/sources/test")
    async def test_source(body: SourceIn) -> dict:
        """Fetch a feed once and show what it found. Saves nothing."""
        if not is_probably_url(body.url):
            raise bad_request("err.source.bad_url")
        url = canonicalise(body.url)
        col = ctx().settings.collection
        async with Fetcher(user_agent=col.user_agent, concurrency=1,
                           per_host_delay_s=0.0, respect_robots=False) as fetcher:
            try:
                response = await fetcher.get(url)
            except FetchError as exc:
                raise bad_request(exc.message_key, detail=exc.detail) from None

        kind = body.kind if body.kind != "auto" else sniff_kind(
            response.text, response.headers.get("content-type", ""))
        if not kind:
            raise bad_request("err.source.unparseable")

        probe = SourceRecord(id="probe", name=body.name or domain_of(url), kind=kind, url=url)
        try:
            items = adapter_for(kind).parse(response.text, probe)
        except Exception as exc:  # noqa: BLE001
            raise bad_request("err.source.unparseable", detail=str(exc)[:200]) from None
        if not items:
            raise bad_request("err.source.empty")
        return {
            "ok": True, "kind": kind, "count": len(items),
            "name": body.name or probe.name,
            "items": [{"title": i.title, "url": i.url, "published_at": i.published_at}
                      for i in items[:5]],
        }

    @api.post("/api/sources")
    async def add_source(body: SourceIn) -> dict:
        app = require_configured()
        if not is_probably_url(body.url):
            raise bad_request("err.source.bad_url")
        url = canonicalise(body.url)
        kind = body.kind
        if kind == "auto":
            probe = await test_source(body)
            kind = probe["kind"]

        base = "".join(c if c.isalnum() else "_" for c in domain_of(url)).strip("_").lower()
        source_id = base or "source"
        n = 2
        while app.store.get_source(source_id) is not None:
            source_id = f"{base}_{n}"
            n += 1

        today = date.today().isoformat()
        record = SourceRecord(
            id=source_id, name=body.name.strip() or domain_of(url), kind=kind, url=url,
            lang=body.lang or "en", region=body.region or "global",
            topics=body.topics or ["general"], interval_min=max(1, body.interval_min),
            status="active", added=today, verified=today,
            expires=(date.today() + timedelta(days=loader.DEFAULT_EXPIRY_DAYS)).isoformat(),
            bundle=loader.LOCAL_BUNDLE)
        try:
            loader.add_local_source(record)
        except loader.BundleError as exc:
            raise bad_request(str(exc)) from None
        app.store.upsert_source(record)
        return {"ok": True, "source": record.to_dict()}

    @api.patch("/api/sources/{source_id}")
    async def patch_source(source_id: str, body: SourcePatch) -> dict:
        app = require_configured()
        record = app.store.get_source(source_id)
        if record is None:
            raise not_found()
        if body.status:
            if body.status not in ("active", "paused", "deprecated", "dead"):
                raise bad_request("err.generic")
            app.store.set_source_status(source_id, body.status)
            # Mirror into the file so a reader who opens it is not misled. The
            # database stays authoritative if the file cannot be written.
            loader.write_status_back(source_id, body.status)
        changes = {k: v for k, v in
                   {"name": body.name, "interval_min": body.interval_min, "lang": body.lang,
                    "region": body.region, "topics": body.topics}.items() if v is not None}
        if changes:
            for key, value in changes.items():
                setattr(record, key, value)
            app.store.upsert_source(record)
            loader.update_local_source(source_id, changes)
        return {"ok": True, "source": (app.store.get_source(source_id) or record).to_dict()}

    @api.delete("/api/sources/{source_id}")
    async def delete_source(source_id: str) -> dict:
        app = require_configured()
        if app.store.get_source(source_id) is None:
            raise not_found()
        app.store.delete_source(source_id)
        loader.remove_local_source(source_id)
        return {"ok": True}

    # ================= actions =============================================
    @api.post("/api/collect")
    async def collect_now() -> dict:
        require_configured()
        if state["collecting"]:
            raise ApiError(409, "err.busy")
        asyncio.get_running_loop().create_task(collect_once())
        return {"started": True}

    @api.post("/api/rescore")
    async def rescore_now() -> dict:
        app = require_configured()
        return {"ok": True, "rescored": rescore(app.store, app.profile)}

    @api.post("/api/enrich")
    async def enrich_now(limit: int = Query(200, ge=1, le=5000)) -> dict:
        from mcpnews.enrich import run_embeddings
        app = require_configured()
        report = await run_embeddings(app.store, app.providers, limit=limit)
        return report.to_dict()

    # ================= static dashboard ====================================
    web = paths.web_dir()

    @api.get("/{full_path:path}")
    async def static_files(full_path: str):
        """Serve the hand-written dashboard. No build step, no CDN, no Node."""
        if full_path.startswith("api/"):
            raise not_found()
        candidate = (web / full_path).resolve() if full_path else (web / "index.html")
        try:
            candidate.relative_to(web.resolve())
        except ValueError:
            raise not_found() from None
        if candidate.is_file() and candidate.suffix in STATIC_SUFFIXES:
            headers = {"Cache-Control": "no-cache"}
            return FileResponse(candidate, headers=headers)
        index = web / "index.html"
        if not index.is_file():
            raise not_found()
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return api
