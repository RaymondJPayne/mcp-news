"""COLLECT and STORE: candidates in, scored articles out.

The order of operations in ``_store_candidate`` is the architecture, not an
implementation detail:

    canonicalise -> already seen? -> capture text -> ARCHIVE -> dedupe -> score

Archiving happens before any relevance decision, because what is not captured on
first fetch is often gone within weeks. Scoring happens last and needs no model,
which is why Tier 0 is a real product rather than a placeholder.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from mcpnews.archive import Archive
from mcpnews.config.profile import Profile
from mcpnews.config.settings import Settings
from mcpnews.ingest.canonical import canonicalise, domain_of
from mcpnews.ingest.extract import extract, summarise
from mcpnews.ingest.fetcher import Fetcher, FetchError
from mcpnews.ingest.simhash import simhash
from mcpnews.rank.scorer import CompiledProfile
from mcpnews.sources.base import CandidateItem
from mcpnews.sources.registry import adapter_for
from mcpnews.store.base import ArticleRecord, ArticleStore, SourceRecord

log = logging.getLogger("mcpnews.collect")

#: How long a source rests after repeated failures, so a dead feed stops costing
#: a request every twenty minutes. Doubles per failure up to a day.
_BACKOFF_BASE_MIN = 15
_BACKOFF_MAX_MIN = 1440


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


@dataclass
class CollectionReport:
    sources_polled: int = 0
    sources_failed: int = 0
    candidates: int = 0
    new_articles: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: _iso(_now()))
    finished_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "sources_polled": self.sources_polled, "sources_failed": self.sources_failed,
            "candidates": self.candidates, "new_articles": self.new_articles,
            "duplicates": self.duplicates, "errors": self.errors[:20],
            "started_at": self.started_at, "finished_at": self.finished_at,
        }


class Collector:
    def __init__(self, settings: Settings, store: ArticleStore, archive: Archive,
                 profile: Profile):
        self.settings = settings
        self.store = store
        self.archive = archive
        self.scorer = CompiledProfile(profile)

    # ---- one pass --------------------------------------------------------
    async def run_once(self, *, source_ids: list[str] | None = None,
                       max_sources: int | None = None) -> CollectionReport:
        report = CollectionReport()
        col = self.settings.collection
        if source_ids:
            sources = [s for s in (self.store.get_source(i) for i in source_ids) if s]
        else:
            sources = self.store.due_sources(_iso(_now()))
        if max_sources:
            sources = sources[:max_sources]
        if not sources:
            report.finished_at = _iso(_now())
            return report

        async with Fetcher(user_agent=col.user_agent, concurrency=col.concurrency,
                           per_host_delay_s=col.per_host_delay_s,
                           respect_robots=col.respect_robots,
                           max_bytes=col.max_body_bytes) as fetcher:
            sem = asyncio.Semaphore(max(1, col.concurrency))

            async def one(source: SourceRecord) -> None:
                async with sem:
                    await self._poll(source, fetcher, report)

            await asyncio.gather(*(one(s) for s in sources), return_exceptions=True)

        report.finished_at = _iso(_now())
        self.store.set_meta("last_collection", report.finished_at)
        return report

    # ---- one source ------------------------------------------------------
    async def _poll(self, source: SourceRecord, fetcher: Fetcher,
                    report: CollectionReport) -> None:
        state = self.store.get_source_state(source.id)
        state.last_run_at = _iso(_now())
        try:
            adapter = adapter_for(source.kind)
            result = await adapter.fetch(source, state, fetcher)
        except (FetchError, NotImplementedError, KeyError, Exception) as exc:
            # A single broken feed must never end a collection run.
            state.consecutive_failures += 1
            state.last_error = f"{type(exc).__name__}: {exc}"[:500]
            state.next_allowed_at = _iso(_now() + timedelta(minutes=self._backoff(
                state.consecutive_failures, source.interval_min)))
            self.store.save_source_state(state)
            report.sources_failed += 1
            report.errors.append(f"{source.id}: {state.last_error}")
            log.warning("source %s failed: %s", source.id, state.last_error)
            return

        report.sources_polled += 1
        if not result.not_modified:
            for candidate in result.items:
                report.candidates += 1
                try:
                    outcome = await self._store_candidate(candidate, source, fetcher)
                except Exception as exc:
                    log.debug("candidate failed (%s): %s", candidate.url, exc)
                    continue
                if outcome == "new":
                    report.new_articles += 1
                    state.article_count += 1
                elif outcome == "duplicate":
                    report.duplicates += 1

        state.consecutive_failures = 0
        state.last_error = None
        state.last_ok_at = _iso(_now())
        state.etag = result.etag or state.etag
        state.last_modified = result.last_modified or state.last_modified
        state.cursor = result.cursor or state.cursor
        state.next_allowed_at = _iso(_now() + timedelta(minutes=max(1, source.interval_min)))
        self.store.save_source_state(state)

    @staticmethod
    def _backoff(failures: int, interval_min: int) -> int:
        return min(_BACKOFF_MAX_MIN, max(interval_min, _BACKOFF_BASE_MIN * (2 ** (failures - 1))))

    # ---- one candidate ---------------------------------------------------
    async def _store_candidate(self, item: CandidateItem, source: SourceRecord,
                               fetcher: Fetcher) -> str:
        try:
            url = canonicalise(item.url)
        except ValueError:
            return "skipped"
        if self.store.find_by_url(url) is not None:
            return "seen"

        domain = domain_of(url)
        body = item.body or ""
        lang = item.lang or source.lang or "en"

        # 3. Capture the text. A failure here is not fatal: the feed's own
        #    summary is still worth storing and searching.
        if not body and self.settings.collection.fetch_fulltext:
            try:
                page = await fetcher.get(url, check_robots=True)
                got = extract(page.text, url=url)
                body = got["body"]
                lang = item.lang or got["lang"] or lang
            except (FetchError, ValueError):
                body = ""

        summary = item.summary or summarise(body)

        # 4. ARCHIVE, before any relevance decision is taken.
        archive_ref = None
        if body:
            archive_ref = self.archive.write(
                canonical_url=url, original_url=item.url, title=item.title, body=body,
                lang=lang, published_at=item.published_at, source_id=source.id)

        # 5. Near-duplicate clustering over the fingerprint of what we captured.
        fingerprint = simhash(f"{item.title}\n{body or summary}")
        cluster_id = self.store.near_duplicate(fingerprint) if fingerprint else None

        # 6. Score. No model, no network, deterministic.
        meta = {"summary": summary, "source_name": source.name, "topics": source.topics,
                "region": source.region, **(item.raw_meta or {})}
        score = self.scorer.score(item.title, body or summary, domain, meta)

        record = ArticleRecord(
            url=url, original_url=item.url, domain=domain, source_id=source.id,
            title=item.title, body=body, summary=summary, lang=lang,
            published_at=item.published_at, fetched_at=_iso(_now()),
            simhash=fingerprint, cluster_id=cluster_id,
            interest_score=score.total,
            matched_rules=[r.to_dict() for r in score.rules],
            scored_at=_iso(_now()), archive_ref=archive_ref,
        )
        try:
            self.store.insert_article(record)
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                return "seen"
            raise
        return "duplicate" if cluster_id is not None else "new"


def rescore(store: ArticleStore, profile: Profile) -> int:
    """Re-rank the whole corpus after a profile edit. No network, no model.

    This is why the stored score must never contain recency: re-scoring history
    against an edited profile has to give the same answer for an article from
    January as for one from this morning.
    """
    compiled = CompiledProfile(profile)
    stamp = _iso(_now())
    count = 0
    for article in list(store.iter_articles()):
        meta = {"summary": article.summary, "region": "", "topics": []}
        score = compiled.score(article.title, article.body or article.summary,
                               article.domain, meta)
        store.update_score(article.id, score.total,
                           [r.to_dict() for r in score.rules], stamp)
        count += 1
    return count
