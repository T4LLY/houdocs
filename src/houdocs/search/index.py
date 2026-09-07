from __future__ import annotations

import hashlib
from collections.abc import Callable

from houdocs.docs.read import DocumentReader
from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.python_docs.read import extract_hom_member, normalize_hom_symbol
from houdocs.python_docs.repository import PythonRepository
from houdocs.search.domain import ALL_SEARCH_NAMESPACES, SearchDomain, namespace_for_document_kind
from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.models import SearchEntry
from houdocs.search.store import SearchStore
from houdocs.vex_docs.repository import VexRepository


SEARCH_SCHEMA_VERSION = "2"
EmbeddingProgress = Callable[[int, int, int, float], None]


class SearchIndexer:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        backend: HybridSearchBackend,
        python_documents: PythonRepository | None = None,
        vex_documents: VexRepository | None = None,
        store: SearchStore,
        embedding_profile: str,
    ) -> None:
        self.documents = documents
        self.python_documents = python_documents or PythonRepository(documents.database)
        self.vex_documents = vex_documents or VexRepository(documents.database)
        self.backend = backend
        self.store = store
        self.embedding_profile = embedding_profile

    def index_all(
        self,
        *,
        embedding_progress: EmbeddingProgress | None = None,
    ) -> dict[str, int]:
        entries = [
            *self._document_entries(),
            *self._hom_entries(),
            *self._vex_entries(),
        ]
        current = {entry.id: entry.content_hash for entry in entries}
        existing: dict[str, tuple[str, str]] = {}
        for namespace in ALL_SEARCH_NAMESPACES:
            existing.update(self.backend.entry_states(namespace))

        stale = sorted(set(existing) - set(current))
        changed = [
            entry
            for entry in entries
            if existing.get(entry.id)
            != (entry.content_hash, self.embedding_profile)
        ]
        if stale:
            self.backend.remove(stale)

        grouped: dict[str, list[SearchEntry]] = {}
        for entry in changed:
            group = str(entry.metadata.get("document_id") or entry.id)
            grouped.setdefault(group, []).append(entry)

        if embedding_progress is not None:
            embedding_total = self.backend.missing_embedding_count(changed)
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

            for group_entries in grouped.values():
                self.backend.upsert(
                    group_entries,
                    embedding_progress=report_embedding,
                )
        else:
            for group_entries in grouped.values():
                self.backend.upsert(group_entries)

        self.store.set_version(SEARCH_SCHEMA_VERSION)
        return {
            "entries": len(current),
            "indexed": len(changed),
            "skipped": len(current) - len(changed),
            "removed": len(stale),
        }

    def _document_entries(self) -> list[SearchEntry]:
        entries: list[SearchEntry] = []
        for section in self.documents.all_sections():
            namespace = namespace_for_document_kind(section.kind)
            if namespace is None:
                continue
            entries.append(
                SearchEntry(
                    id=f"{namespace}:{section.section_id}",
                    namespace=namespace,
                    source_id=section.section_id,
                    content=section.text,
                    content_hash=section.content_hash,
                    embedding_profile=self.embedding_profile,
                    token_count=section.token_count,
                    metadata=dict(section.metadata),
                )
            )
        return entries

    def _hom_entries(self) -> list[SearchEntry]:
        document_reader = DocumentReader(self.documents)
        page_cache: dict[str, str] = {}
        entries: list[SearchEntry] = []
        for record in self.python_documents.all():
            try:
                canonical = normalize_hom_symbol(record.symbol)
            except HouDocsError as exc:
                if exc.error.code != "hom_document_invalid_symbol":
                    raise
                continue
            if canonical.casefold() != record.symbol.casefold():
                continue

            document = self.documents.document(record.document_id)
            page_text = page_cache.get(record.document_id)
            if page_text is None:
                page_text = str(document_reader.page(document)["text"])
                page_cache[record.document_id] = page_text

            text = page_text
            if record.kind in {"method", "function"} and record.member_name:
                block = extract_hom_member(page_text, record.member_name)
                if block is None:
                    continue
                _signature, text = block

            content = _specialized_content(record.symbol, record.signatures, text)
            entries.append(
                SearchEntry(
                    id=f"hom:{record.symbol}",
                    namespace=SearchDomain.HOM.value,
                    source_id=record.symbol,
                    content=content,
                    content_hash=_content_hash(content),
                    embedding_profile=self.embedding_profile,
                    metadata={
                        "document_id": record.document_id,
                        "symbol": record.symbol,
                        "parent_symbol": record.parent_symbol,
                        "member_name": record.member_name,
                        "member_kind": record.kind,
                    },
                )
            )
        return entries

    def _vex_entries(self) -> list[SearchEntry]:
        document_reader = DocumentReader(self.documents)
        page_cache: dict[str, str] = {}
        entries: list[SearchEntry] = []
        for record in self.vex_documents.all():
            document = self.documents.document(record.document_id)
            text = page_cache.get(record.document_id)
            if text is None:
                text = str(document_reader.page(document)["text"])
                page_cache[record.document_id] = text
            content = _specialized_content(
                record.function_name,
                record.signatures,
                text,
            )
            entries.append(
                SearchEntry(
                    id=f"vex:{record.function_name}",
                    namespace=SearchDomain.VEX.value,
                    source_id=record.function_name,
                    content=content,
                    content_hash=_content_hash(content),
                    embedding_profile=self.embedding_profile,
                    metadata={
                        "document_id": record.document_id,
                        "function": record.function_name,
                    },
                )
            )
        return entries


def _specialized_content(
    symbol: str,
    signatures: tuple[str, ...],
    text: str,
) -> str:
    return "\n".join(part for part in (symbol, *signatures, text) if part).strip()


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
