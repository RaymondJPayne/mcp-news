"""SQLite backend. One file, no services, FTS5 for keyword search.

The humble default is deliberate: a project that needs four containers before it
shows its first article has already lost most of the people it was written for.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mcpnews.ingest.simhash import DEFAULT_MAX_DISTANCE
from mcpnews.store.base import (
    ENRICHMENT_CAPABILITIES,
    ArticleRecord,
    ArticleStore,
    SourceRecord,
    SourceState,
    register,
)

SCHEMA_VERSION = 1
_BITS = 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id            TEXT PRIMARY KEY,
    bundle        TEXT NOT NULL DEFAULT 'local',
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL,
    url           TEXT NOT NULL,
    lang          TEXT NOT NULL DEFAULT 'en',
    region        TEXT NOT NULL DEFAULT 'global',
    topics        TEXT NOT NULL DEFAULT '[]',
    interval_min  INTEGER NOT NULL DEFAULT 60,
    status        TEXT NOT NULL DEFAULT 'active',
    added         TEXT,
    verified      TEXT,
    expires       TEXT,
    replaced_by   TEXT,
    notes         TEXT,
    config        TEXT NOT NULL DEFAULT '{}',
    auth          TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_state (
    source_id            TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    cursor               TEXT,
    etag                 TEXT,
    last_modified        TEXT,
    last_run_at          TEXT,
    last_ok_at           TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error           TEXT,
    next_allowed_at      TEXT,
    article_count        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS articles (
    id               INTEGER PRIMARY KEY,
    url              TEXT NOT NULL UNIQUE,
    original_url     TEXT NOT NULL,
    domain           TEXT NOT NULL,
    source_id        TEXT,
    title            TEXT NOT NULL,
    title_translated TEXT,
    summary          TEXT NOT NULL DEFAULT '',
    body             TEXT NOT NULL DEFAULT '',
    lang             TEXT NOT NULL DEFAULT 'en',
    published_at     TEXT,
    fetched_at       TEXT NOT NULL,
    simhash          INTEGER NOT NULL DEFAULT 0,
    -- Eight 8-bit bands of the fingerprint. Two hashes within seven bits of each
    -- other must share at least one whole band, so an OR over these eight indexed
    -- columns finds every near-duplicate the threshold admits.
    b0 INTEGER NOT NULL DEFAULT 0, b1 INTEGER NOT NULL DEFAULT 0,
    b2 INTEGER NOT NULL DEFAULT 0, b3 INTEGER NOT NULL DEFAULT 0,
    b4 INTEGER NOT NULL DEFAULT 0, b5 INTEGER NOT NULL DEFAULT 0,
    b6 INTEGER NOT NULL DEFAULT 0, b7 INTEGER NOT NULL DEFAULT 0,
    cluster_id       INTEGER,
    interest_score   REAL NOT NULL DEFAULT 0,
    matched_rules    TEXT NOT NULL DEFAULT '[]',
    scored_at        TEXT,
    archive_ref      TEXT,
    embedded    TEXT NOT NULL DEFAULT 'pending',
    translated  TEXT NOT NULL DEFAULT 'pending',
    contextual  TEXT NOT NULL DEFAULT 'pending',
    entities    TEXT NOT NULL DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_score ON articles(interest_score DESC);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_articles_cluster ON articles(cluster_id);
CREATE INDEX IF NOT EXISTS idx_articles_b0 ON articles(b0);
CREATE INDEX IF NOT EXISTS idx_articles_b1 ON articles(b1);
CREATE INDEX IF NOT EXISTS idx_articles_b2 ON articles(b2);
CREATE INDEX IF NOT EXISTS idx_articles_b3 ON articles(b3);
CREATE INDEX IF NOT EXISTS idx_articles_b4 ON articles(b4);
CREATE INDEX IF NOT EXISTS idx_articles_b5 ON articles(b5);
CREATE INDEX IF NOT EXISTS idx_articles_b6 ON articles(b6);
CREATE INDEX IF NOT EXISTS idx_articles_b7 ON articles(b7);

-- Vectors record their model. Vectors from different models are not comparable,
-- so the query side always filters on model_id rather than mixing spaces.
CREATE TABLE IF NOT EXISTS article_vectors (
    article_id  INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    model_id    TEXT NOT NULL,
    dimensions  INTEGER NOT NULL,
    vector      BLOB NOT NULL,
    PRIMARY KEY (article_id, model_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    title, body, content='articles', content_rowid='id', tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
    INSERT INTO articles_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, title, body)
    VALUES ('delete', old.id, old.title, old.body);
END;
CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE OF title, body ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, title, body)
    VALUES ('delete', old.id, old.title, old.body);
    INSERT INTO articles_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _iso_days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")


def _signed(value: int) -> int:
    """SQLite INTEGER is signed 64-bit; a fingerprint is unsigned 64-bit.

    Storing the raw value overflows. Reinterpreting the same bits as signed is
    lossless and keeps Hamming distance intact, which is all we compare on.
    """
    value &= 0xFFFFFFFFFFFFFFFF
    return value - (1 << 64) if value >= (1 << 63) else value


def _unsigned(value: int) -> int:
    return value & 0xFFFFFFFFFFFFFFFF


#: Eight bands of eight bits. By the pigeonhole principle two fingerprints that
#: differ in at most seven bits share at least one identical band, so blocking on
#: these loses no candidate the distance threshold would have accepted.
_BAND_COUNT = 8
_BAND_BITS = _BITS // _BAND_COUNT


def _bands(simhash: int) -> tuple[int, ...]:
    h = simhash & 0xFFFFFFFFFFFFFFFF
    return tuple((h >> (i * _BAND_BITS)) & 0xFF for i in range(_BAND_COUNT))


def _hamming(a: int, b: int) -> int:
    return bin((a ^ b) & 0xFFFFFFFFFFFFFFFF).count("1")


def _fts_query(raw: str) -> str:
    """Turn free text into an FTS5 query without letting its operators through.

    A reader typing ``AND`` or a stray quotation mark should get results, not a
    syntax error from a database they did not know existed.
    """
    tokens = [t for t in "".join(c if c.isalnum() or c in "-_'" else " " for c in raw).split() if t]
    if not tokens:
        return ""
    return " ".join(f'"{t}"' for t in tokens)


@register("sqlite")
class SQLiteStore(ArticleStore):
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()

    # ---- connection ------------------------------------------------------
    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def initialise(self) -> None:
        with self._write_lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),))

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ---- meta ------------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._write_lock:
            self._conn.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    # ---- sources ---------------------------------------------------------
    def upsert_source(self, source: SourceRecord) -> bool:
        with self._write_lock:
            exists = self._conn.execute(
                "SELECT 1 FROM sources WHERE id=?", (source.id,)).fetchone() is not None
            now = _now()
            if exists:
                # status is deliberately absent: the database is authoritative for
                # it once a source is registered. docs/SOURCES.md §3.
                self._conn.execute(
                    "UPDATE sources SET bundle=?, name=?, kind=?, url=?, lang=?, region=?,"
                    " topics=?, interval_min=?, added=?, verified=?, expires=?, replaced_by=?,"
                    " notes=?, config=?, auth=?, updated_at=? WHERE id=?",
                    (source.bundle, source.name, source.kind, source.url, source.lang,
                     source.region, json.dumps(source.topics), source.interval_min,
                     source.added, source.verified, source.expires, source.replaced_by,
                     source.notes, json.dumps(source.config), json.dumps(source.auth),
                     now, source.id))
                return False
            self._conn.execute(
                "INSERT INTO sources(id,bundle,name,kind,url,lang,region,topics,interval_min,"
                "status,added,verified,expires,replaced_by,notes,config,auth,created_at,"
                "updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (source.id, source.bundle, source.name, source.kind, source.url, source.lang,
                 source.region, json.dumps(source.topics), source.interval_min, source.status,
                 source.added, source.verified, source.expires, source.replaced_by,
                 source.notes, json.dumps(source.config), json.dumps(source.auth), now, now))
            self._conn.execute(
                "INSERT OR IGNORE INTO source_state(source_id) VALUES(?)", (source.id,))
            return True

    def set_source_status(self, source_id: str, status: str) -> None:
        with self._write_lock:
            self._conn.execute("UPDATE sources SET status=?, updated_at=? WHERE id=?",
                               (status, _now(), source_id))

    def delete_source(self, source_id: str) -> None:
        with self._write_lock:
            self._conn.execute("DELETE FROM sources WHERE id=?", (source_id,))

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> SourceRecord:
        return SourceRecord(
            id=row["id"], bundle=row["bundle"], name=row["name"], kind=row["kind"],
            url=row["url"], lang=row["lang"], region=row["region"],
            topics=json.loads(row["topics"] or "[]"), interval_min=row["interval_min"],
            status=row["status"], added=row["added"], verified=row["verified"],
            expires=row["expires"], replaced_by=row["replaced_by"], notes=row["notes"],
            config=json.loads(row["config"] or "{}"), auth=json.loads(row["auth"] or "{}"))

    def get_source(self, source_id: str) -> SourceRecord | None:
        row = self._conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        return self._source_from_row(row) if row else None

    def list_sources(self, status: str | None = None) -> list[SourceRecord]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM sources WHERE status=? ORDER BY bundle, name", (status,))
        else:
            rows = self._conn.execute("SELECT * FROM sources ORDER BY bundle, name")
        return [self._source_from_row(r) for r in rows]

    def get_source_state(self, source_id: str) -> SourceState:
        row = self._conn.execute(
            "SELECT * FROM source_state WHERE source_id=?", (source_id,)).fetchone()
        if not row:
            return SourceState(source_id=source_id)
        return SourceState(
            source_id=row["source_id"], cursor=row["cursor"], etag=row["etag"],
            last_modified=row["last_modified"], last_run_at=row["last_run_at"],
            last_ok_at=row["last_ok_at"], consecutive_failures=row["consecutive_failures"],
            last_error=row["last_error"], next_allowed_at=row["next_allowed_at"],
            article_count=row["article_count"])

    def save_source_state(self, state: SourceState) -> None:
        with self._write_lock:
            self._conn.execute(
                "INSERT INTO source_state(source_id,cursor,etag,last_modified,last_run_at,"
                "last_ok_at,consecutive_failures,last_error,next_allowed_at,article_count)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(source_id) DO UPDATE SET cursor=excluded.cursor,"
                " etag=excluded.etag, last_modified=excluded.last_modified,"
                " last_run_at=excluded.last_run_at, last_ok_at=excluded.last_ok_at,"
                " consecutive_failures=excluded.consecutive_failures,"
                " last_error=excluded.last_error, next_allowed_at=excluded.next_allowed_at,"
                " article_count=excluded.article_count",
                (state.source_id, state.cursor, state.etag, state.last_modified,
                 state.last_run_at, state.last_ok_at, state.consecutive_failures,
                 state.last_error, state.next_allowed_at, state.article_count))

    def due_sources(self, now_iso: str) -> list[SourceRecord]:
        rows = self._conn.execute(
            "SELECT s.* FROM sources s LEFT JOIN source_state st ON st.source_id = s.id"
            " WHERE s.status IN ('active','deprecated')"
            "   AND (st.next_allowed_at IS NULL OR st.next_allowed_at <= ?)"
            " ORDER BY COALESCE(st.last_run_at, '') ASC", (now_iso,))
        return [self._source_from_row(r) for r in rows]

    # ---- articles --------------------------------------------------------
    def find_by_url(self, canonical_url: str) -> int | None:
        row = self._conn.execute("SELECT id FROM articles WHERE url=?",
                                 (canonical_url,)).fetchone()
        return int(row["id"]) if row else None

    def insert_article(self, a: ArticleRecord) -> int:
        bands = _bands(a.simhash)
        columns = ["url", "original_url", "domain", "source_id", "title", "title_translated",
                   "summary", "body", "lang", "published_at", "fetched_at", "simhash",
                   *[f"b{i}" for i in range(_BAND_COUNT)],
                   "cluster_id", "interest_score", "matched_rules", "scored_at", "archive_ref",
                   *ENRICHMENT_CAPABILITIES]
        values = [a.url, a.original_url, a.domain, a.source_id, a.title, a.title_translated,
                  a.summary, a.body, a.lang, a.published_at, a.fetched_at or _now(),
                  _signed(a.simhash), *bands,
                  a.cluster_id, a.interest_score, json.dumps(a.matched_rules), a.scored_at,
                  a.archive_ref,
                  *[a.enrichment.get(c, "pending") for c in ENRICHMENT_CAPABILITIES]]
        sql = (f"INSERT INTO articles({','.join(columns)})"
               f" VALUES({','.join('?' * len(columns))})")
        with self._write_lock:
            cur = self._conn.execute(sql, values)
            article_id = int(cur.lastrowid)
            if a.cluster_id is None:
                self._conn.execute("UPDATE articles SET cluster_id=? WHERE id=?",
                                   (article_id, article_id))
            if a.source_id:
                self._conn.execute(
                    "UPDATE source_state SET article_count = article_count + 1 "
                    "WHERE source_id=?", (a.source_id,))
        return article_id

    @staticmethod
    def _article_from_row(row: sqlite3.Row, *, with_body: bool = True) -> ArticleRecord:
        keys = row.keys()
        return ArticleRecord(
            id=int(row["id"]), url=row["url"], original_url=row["original_url"],
            domain=row["domain"], source_id=row["source_id"], title=row["title"],
            title_translated=row["title_translated"], summary=row["summary"],
            body=row["body"] if with_body and "body" in keys else "",
            lang=row["lang"], published_at=row["published_at"], fetched_at=row["fetched_at"],
            simhash=_unsigned(int(row["simhash"])) if "simhash" in keys else 0,
            cluster_id=row["cluster_id"], interest_score=row["interest_score"],
            matched_rules=json.loads(row["matched_rules"] or "[]"),
            scored_at=row["scored_at"], archive_ref=row["archive_ref"],
            enrichment={c: (row[c] if c in keys else "pending")
                        for c in ENRICHMENT_CAPABILITIES})

    def get_article(self, article_id: int) -> ArticleRecord | None:
        row = self._conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
        return self._article_from_row(row) if row else None

    def update_score(self, article_id: int, score: float, rules: list[dict],
                     scored_at: str) -> None:
        with self._write_lock:
            self._conn.execute(
                "UPDATE articles SET interest_score=?, matched_rules=?, scored_at=? WHERE id=?",
                (float(score), json.dumps(rules), scored_at, article_id))

    def set_enrichment(self, article_id: int, capability: str, state: str) -> None:
        if capability not in ENRICHMENT_CAPABILITIES:
            raise KeyError(f"unknown capability {capability!r}")
        with self._write_lock:
            self._conn.execute(
                f"UPDATE articles SET {capability}=? WHERE id=?", (state, article_id))

    def near_duplicate(self, simhash: int, *, within_days: int = 7,
                       max_distance: int | None = None) -> int | None:
        if not simhash:
            return None
        max_distance = DEFAULT_MAX_DISTANCE if max_distance is None else max_distance
        bands = _bands(simhash)
        since = _iso_days_ago(within_days)
        where = " OR ".join(f"b{i}=?" for i in range(_BAND_COUNT))
        rows = self._conn.execute(
            "SELECT id, simhash, cluster_id FROM articles"
            f" WHERE fetched_at >= ? AND ({where}) LIMIT 3000",
            (since, *bands))
        for row in rows:
            if _hamming(_unsigned(int(row["simhash"])), simhash) <= max_distance:
                return int(row["cluster_id"] or row["id"])
        return None

    def iter_articles(self, *, batch: int = 500) -> Iterable[ArticleRecord]:
        last = 0
        while True:
            rows = self._conn.execute(
                "SELECT * FROM articles WHERE id > ? ORDER BY id LIMIT ?",
                (last, batch)).fetchall()
            if not rows:
                return
            for row in rows:
                last = int(row["id"])
                yield self._article_from_row(row)

    # ---- reading ---------------------------------------------------------
    def feed(self, *, hours: int, limit: int, min_score: float,
             half_life_h: float | None) -> list[ArticleRecord]:
        since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
        rows = self._conn.execute(
            "SELECT id,url,original_url,domain,source_id,title,title_translated,summary,"
            " lang,published_at,fetched_at,cluster_id,interest_score,matched_rules,scored_at,"
            " archive_ref,embedded,translated,contextual,entities FROM articles"
            " WHERE interest_score >= ?"
            "   AND COALESCE(published_at, fetched_at) >= ?"
            "   AND (cluster_id IS NULL OR cluster_id = id)"
            " ORDER BY interest_score DESC LIMIT ?",
            (float(min_score), since, max(limit * 5, limit))).fetchall()
        articles = [self._article_from_row(r, with_body=False) for r in rows]

        # Decay is applied here, as a view. Nothing is written back.
        from mcpnews.search.views import display_score
        articles.sort(
            key=lambda a: display_score(a.interest_score, a.published_at or a.fetched_at,
                                        half_life_h),
            reverse=True)
        return articles[:limit]

    def keyword_search(self, query: str, *, limit: int = 20, days: int | None = 90,
                       lang: str | None = None) -> list[tuple[ArticleRecord, float, str]]:
        match = _fts_query(query)
        if not match:
            return []
        sql = [("SELECT a.*, bm25(articles_fts) AS rel,"
                " snippet(articles_fts, 1, '', '', '…', 18) AS snip"
                " FROM articles_fts JOIN articles a ON a.id = articles_fts.rowid"
                " WHERE articles_fts MATCH ?")]
        params: list[Any] = [match]
        if days:
            sql.append(" AND COALESCE(a.published_at, a.fetched_at) >= ?")
            params.append(_iso_days_ago(days))
        if lang:
            sql.append(" AND a.lang = ?")
            params.append(lang)
        sql.append(" ORDER BY rel LIMIT ?")
        params.append(limit)
        rows = self._conn.execute("".join(sql), params).fetchall()
        out = []
        for row in rows:
            article = self._article_from_row(row, with_body=False)
            # bm25 returns lower-is-better; invert so callers always sort descending.
            out.append((article, -float(row["rel"]), (row["snip"] or "").strip()))
        return out

    def timeline(self, term: str, *, days: int = 90,
                 bucket: str = "day") -> list[tuple[str, int]]:
        match = _fts_query(term)
        if not match:
            return []
        fmt = "%Y-%m-%dT%H" if bucket == "hour" else "%Y-%m-%d"
        rows = self._conn.execute(
            "SELECT strftime(?, COALESCE(a.published_at, a.fetched_at)) AS t, COUNT(*) AS n"
            " FROM articles_fts JOIN articles a ON a.id = articles_fts.rowid"
            " WHERE articles_fts MATCH ? AND COALESCE(a.published_at, a.fetched_at) >= ?"
            " GROUP BY t ORDER BY t", (fmt, match, _iso_days_ago(days))).fetchall()
        return [(r["t"], int(r["n"])) for r in rows if r["t"]]

    # ---- vectors ---------------------------------------------------------
    def pending_embedding(self, limit: int = 100) -> list[ArticleRecord]:
        rows = self._conn.execute(
            "SELECT * FROM articles WHERE embedded='pending'"
            " ORDER BY interest_score DESC, id DESC LIMIT ?", (limit,)).fetchall()
        return [self._article_from_row(r) for r in rows]

    def save_vector(self, article_id: int, model_id: str, vector: list[float]) -> None:
        import array
        blob = array.array("f", vector).tobytes()
        with self._write_lock:
            self._conn.execute(
                "INSERT INTO article_vectors(article_id, model_id, dimensions, vector)"
                " VALUES(?,?,?,?) ON CONFLICT(article_id, model_id) DO UPDATE SET"
                " vector=excluded.vector, dimensions=excluded.dimensions",
                (article_id, model_id, len(vector), blob))

    def vector_search(self, vector: list[float], model_id: str, *, limit: int = 20,
                      days: int | None = 90) -> list[tuple[ArticleRecord, float]]:
        """Brute-force cosine similarity inside one model's space.

        Deliberately simple. sqlite-vec is an optional extra and an ANN index is
        a Phase 5 concern; at the corpus size a single reader accumulates, a
        linear scan over a few tens of thousands of vectors is milliseconds, and
        it means Tier 1 works with nothing extra installed.
        """
        import array
        import math

        params: list[Any] = [model_id]
        sql = [("SELECT v.article_id, v.vector FROM article_vectors v"
                " JOIN articles a ON a.id = v.article_id WHERE v.model_id = ?")]
        if days:
            sql.append(" AND COALESCE(a.published_at, a.fetched_at) >= ?")
            params.append(_iso_days_ago(days))
        rows = self._conn.execute("".join(sql), params).fetchall()
        if not rows:
            return []

        qnorm = math.sqrt(sum(x * x for x in vector)) or 1.0
        scored: list[tuple[int, float]] = []
        for row in rows:
            other = array.array("f")
            other.frombytes(row["vector"])
            if len(other) != len(vector):
                continue          # a different space; never mix them
            dot = sum(a * b for a, b in zip(vector, other, strict=True))
            norm = math.sqrt(sum(b * b for b in other)) or 1.0
            scored.append((int(row["article_id"]), dot / (qnorm * norm)))
        scored.sort(key=lambda t: t[1], reverse=True)

        out: list[tuple[ArticleRecord, float]] = []
        for article_id, similarity in scored[:limit]:
            article = self.get_article(article_id)
            if article is not None:
                article.body = ""
                out.append((article, similarity))
        return out

    def vector_spaces(self) -> list[tuple[str, int]]:
        rows = self._conn.execute(
            "SELECT model_id, COUNT(*) AS n FROM article_vectors GROUP BY model_id").fetchall()
        return [(r["model_id"], int(r["n"])) for r in rows]

    def counts(self) -> dict[str, int]:
        one = lambda sql, *p: int(self._conn.execute(sql, p).fetchone()[0])  # noqa: E731
        return {
            "articles": one("SELECT COUNT(*) FROM articles"),
            "enriched": one("SELECT COUNT(*) FROM articles WHERE embedded='done'"),
            "queued": one("SELECT COUNT(*) FROM articles WHERE embedded='pending'"),
            "clusters": one("SELECT COUNT(DISTINCT COALESCE(cluster_id, id)) FROM articles"),
            "sources_active": one("SELECT COUNT(*) FROM sources WHERE status='active'"),
            "sources_failing": one(
                "SELECT COUNT(*) FROM source_state WHERE consecutive_failures >= 3"),
        }
