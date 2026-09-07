from __future__ import annotations

from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.python_docs.repository import PythonRepository
from houdocs.search.domain import ALL_SEARCH_NAMESPACES, SearchDomain
from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.models import SearchHit
from houdocs.search.rrf import normalize_rrf_score
from houdocs.vex_docs.repository import VexRepository


def _search_path(document: str, heading_path: tuple[str, ...] | list[str]) -> list[str]:
    path = [document]
    for heading in heading_path:
        if not heading or heading == path[-1]:
            continue
        path.append(heading)
    return path


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
        return {"hits": output}

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
            "path": _search_path(document.title, section.heading_path),
            "kind": section.kind,
            "score": normalize_rrf_score(hit.score),
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
            "path": _search_path(document.title, heading_path),
            "kind": document.kind,
            "score": normalize_rrf_score(hit.score),
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
            "path": _search_path(document.title, [record.function_name]),
            "kind": document.kind,
            "score": normalize_rrf_score(hit.score),
        }
