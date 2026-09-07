from __future__ import annotations

from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.python_docs.repository import PythonRepository
from houdocs.search.domain import ALL_SEARCH_NAMESPACES, SearchDomain
from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.models import SearchHit
from houdocs.search.rrf import normalize_rrf_score
from houdocs.vex_docs.repository import VexRepository


class DocumentSearchService:
    def __init__(
        self,
        *,
        repository: DocumentRepository,
        backend: HybridSearchBackend,
        python_repository: PythonRepository | None = None,
        vex_repository: VexRepository | None = None,
    ) -> None:
        self.repository = repository
        self.python_repository = python_repository or PythonRepository(repository.database)
        self.vex_repository = vex_repository or VexRepository(repository.database)
        self.backend = backend

    def search(
        self,
        query: str,
        *,
        domain: SearchDomain | None = None,
        top_k: int = 10,
    ) -> dict[str, object]:
        namespaces = [domain.value] if domain is not None else list(ALL_SEARCH_NAMESPACES)
        hits = self.backend.search(query, namespaces=namespaces, top_k=top_k)
        output: list[dict[str, object]] = []
        for hit in hits:
            rendered = self._render_hit(hit)
            if rendered is not None:
                output.append(rendered)
        return {"query": query, "hits": output}

    def _render_hit(self, hit: SearchHit) -> dict[str, object] | None:
        if hit.namespace in {SearchDomain.NODE.value, SearchDomain.DOCUMENT.value}:
            return self._document_hit(hit)
        if hit.namespace == SearchDomain.HOM.value:
            return self._hom_hit(hit)
        if hit.namespace == SearchDomain.VEX.value:
            return self._vex_hit(hit)
        return None

    def _document_hit(self, hit: SearchHit) -> dict[str, object] | None:
        try:
            section = self.repository.section(hit.source_id)
            document = self.repository.document(section.document_id)
        except HouDocsError as exc:
            if exc.error.code not in {
                "document_section_not_found",
                "document_not_found",
            }:
                raise
            return None
        return {
            "section_id": section.section_id,
            "score": normalize_rrf_score(hit.score),
            "document": document.title,
            "heading": section.heading,
            "heading_path": list(section.heading_path),
            "kind": section.kind,
            "relative_path": document.relative_path,
            "anchor": section.anchor,
        }

    def _hom_hit(self, hit: SearchHit) -> dict[str, object] | None:
        record = self.python_repository.get(hit.source_id)
        if record is None:
            return None
        try:
            document = self.repository.document(record.document_id)
        except HouDocsError as exc:
            if exc.error.code != "document_not_found":
                raise
            return None
        heading_path = (
            [record.parent_symbol, record.member_name]
            if record.parent_symbol and record.member_name
            else [record.symbol]
        )
        return {
            "section_id": hit.id,
            "score": normalize_rrf_score(hit.score),
            "document": document.title,
            "heading": record.member_name or record.symbol,
            "heading_path": heading_path,
            "kind": document.kind,
            "relative_path": document.relative_path,
            "anchor": None,
        }

    def _vex_hit(self, hit: SearchHit) -> dict[str, object] | None:
        record = self.vex_repository.get(hit.source_id)
        if record is None:
            return None
        try:
            document = self.repository.document(record.document_id)
        except HouDocsError as exc:
            if exc.error.code != "document_not_found":
                raise
            return None
        return {
            "section_id": hit.id,
            "score": normalize_rrf_score(hit.score),
            "document": document.title,
            "heading": record.function_name,
            "heading_path": [record.function_name],
            "kind": document.kind,
            "relative_path": document.relative_path,
            "anchor": None,
        }
