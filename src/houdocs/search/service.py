from __future__ import annotations

from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.rrf import normalize_rrf_score


class DocumentSearchService:
    def __init__(
        self, *, repository: DocumentRepository, backend: HybridSearchBackend
    ) -> None:
        self.repository = repository
        self.backend = backend

    def search(self, query: str, *, top_k: int = 10) -> dict[str, object]:
        hits = self.backend.search(query, namespaces=["docs"], top_k=top_k)
        output: list[dict[str, object]] = []
        for hit in hits:
            try:
                section = self.repository.section(hit.source_id)
                document = self.repository.document(section.document_id)
            except HouDocsError as exc:
                if exc.error.code not in {
                    "document_section_not_found",
                    "document_not_found",
                }:
                    raise
                continue
            output.append(
                {
                    "section_id": section.section_id,
                    "score": normalize_rrf_score(hit.score),
                    "document": document.title,
                    "heading": section.heading,
                    "heading_path": list(section.heading_path),
                    "kind": section.kind,
                    "relative_path": document.relative_path,
                    "anchor": section.anchor,
                }
            )
        return {"query": query, "hits": output}
