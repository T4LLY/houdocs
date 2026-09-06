from __future__ import annotations

from houdocs.docs.repository import DocumentRepository
from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.models import SearchEntry
from houdocs.search.store import SearchStore


SEARCH_SCHEMA_VERSION = "1"


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

    def index_all(self) -> dict[str, int]:
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
        if stale:
            self.backend.remove(stale)
        if changed:
            self.backend.upsert(
                [
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
            )
        self.store.set_version(SEARCH_SCHEMA_VERSION)
        return {
            "entries": len(current),
            "indexed": len(changed),
            "skipped": len(current) - len(changed),
            "removed": len(stale),
        }
