from __future__ import annotations

from collections.abc import Callable

from houdocs.docs.repository import DocumentRepository
from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.models import SearchEntry
from houdocs.search.store import SearchStore


SEARCH_SCHEMA_VERSION = "1"
EmbeddingProgress = Callable[[int, int, int, float], None]


class SearchIndexer:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        backend: HybridSearchBackend,
        store: SearchStore,
        embedding_profile: str,
    ) -> None:
        self.documents = documents
        self.backend = backend
        self.store = store
        self.embedding_profile = embedding_profile

    def index_all(
        self,
        *,
        embedding_progress: EmbeddingProgress | None = None,
    ) -> dict[str, int]:
        sections = self.documents.all_sections()
        current = {section.section_id: section.content_hash for section in sections}
        existing = self.backend.entry_states("docs")
        stale = sorted(set(existing) - set(current))
        changed = [
            section
            for section in sections
            if existing.get(section.section_id)
            != (section.content_hash, self.embedding_profile)
        ]
        entries = [
            SearchEntry(
                id=section.section_id,
                namespace="docs",
                source_id=section.section_id,
                content=section.text,
                content_hash=section.content_hash,
                embedding_profile=self.embedding_profile,
                token_count=section.token_count,
                metadata=dict(section.metadata),
            )
            for section in changed
        ]
        if stale:
            self.backend.remove(stale)
        if embedding_progress is not None:
            embedding_total = self.backend.missing_embedding_count(entries)
            embedding_completed = 0
            embedding_progress(0, embedding_total, 0, 0.0)

            def report_embedding(batch_count: int, batch_seconds: float) -> None:
                nonlocal embedding_completed
                embedding_completed += batch_count
                embedding_progress(
                    embedding_completed,
                    embedding_total,
                    batch_count,
                    batch_seconds,
                )

            if entries:
                self.backend.upsert(entries, embedding_progress=report_embedding)
        elif entries:
            self.backend.upsert(entries)
        self.store.set_version(SEARCH_SCHEMA_VERSION)
        return {
            "entries": len(current),
            "indexed": len(changed),
            "skipped": len(current) - len(changed),
            "removed": len(stale),
        }
