"""The only stage that needs a model, and the only optional one.

Every capability tracks its own state per article, so a corpus collected with no
model at all can be enriched months later, in relevance order. Collect now,
understand later, is the intended workflow rather than a fallback.

Implemented in this release: embeddings, which is what turns Tier 0 into Tier 1.
Translation, per-article context and entity extraction have their state columns
and their queue position, and are honestly reported as not yet implemented — see
docs/ROADMAP.md.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from mcpnews.providers.chain import NoProviderAvailable
from mcpnews.providers.registry import ProviderRegistry
from mcpnews.store.base import ArticleStore

log = logging.getLogger("mcpnews.enrich")

#: How much of an article is embedded. Long enough to carry the subject, short
#: enough that a local model on a laptop keeps up.
_EMBED_CHARS = 2000


@dataclass
class EnrichReport:
    embedded: int = 0
    failed: int = 0
    skipped: int = 0
    model_id: str = ""
    note_key: str | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"embedded": self.embedded, "failed": self.failed, "skipped": self.skipped,
                "model_id": self.model_id, "note_key": self.note_key,
                "errors": self.errors[:10]}


def embed_text(title: str, summary: str, body: str) -> str:
    return f"{title}\n\n{(summary or body or '')[:_EMBED_CHARS]}".strip()


async def run_embeddings(store: ArticleStore, providers: ProviderRegistry, *,
                         limit: int = 200, batch: int = 32) -> EnrichReport:
    """Process the embedding backlog, highest interest score first.

    A provider going down mid-run leaves everything not yet processed marked
    ``pending`` and returns cleanly. Nothing is lost and the next run resumes.
    """
    report = EnrichReport()
    if not providers.has_embed():
        report.note_key = "settings.providers.none"
        return report

    pending = store.pending_embedding(limit=limit)
    if not pending:
        return report

    for start in range(0, len(pending), batch):
        chunk = pending[start:start + batch]
        texts = [embed_text(a.title, a.summary, a.body) for a in chunk]
        try:
            vectors, _slot, model_id = await providers.embed(texts)
        except NoProviderAvailable:
            report.note_key = "err.provider.unreachable"
            break
        except Exception as exc:
            report.errors.append(str(exc)[:200])
            for a in chunk:
                store.set_enrichment(a.id, "embedded", "failed")
                report.failed += 1
            continue
        report.model_id = model_id or report.model_id
        for article, vector in zip(chunk, vectors, strict=False):
            try:
                store.save_vector(article.id, model_id, vector)
                store.set_enrichment(article.id, "embedded", "done")
                report.embedded += 1
            except NotImplementedError:
                store.set_enrichment(article.id, "embedded", "skipped")
                report.skipped += 1
    return report
