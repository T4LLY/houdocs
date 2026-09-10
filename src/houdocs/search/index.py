from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable

from houdocs.docs.models import DocumentSection
from houdocs.docs.repository import DocumentRepository
from houdocs.docs.text import compose_document_text
from houdocs.errors import HouDocsError
from houdocs.python_docs.text import extract_hom_member, normalize_hom_symbol
from houdocs.python_docs.repository import PythonRepository
from houdocs.search.domain import SearchDomain, namespace_for_document_kind
from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.models import SearchEntry
from houdocs.search.tokens import count_openai_tokens
from houdocs.vex_docs.parser import normalize_vex_text
from houdocs.vex_docs.repository import VexRepository

EmbeddingProgress = Callable[[int, int, int, float], None]
TokenCounter = Callable[[str], int]
EntryGroups = dict[str, list[SearchEntry]]


class SearchIndexer:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        backend: HybridSearchBackend,
        python_documents: PythonRepository | None = None,
        vex_documents: VexRepository | None = None,
        embedding_profile: str,
        token_counter: TokenCounter = count_openai_tokens,
    ) -> None:
        self.documents = documents
        self.python_documents = python_documents or PythonRepository(documents.database)
        self.vex_documents = vex_documents or VexRepository(documents.database)
        self.backend = backend
        self.embedding_profile = embedding_profile
        self.token_counter = token_counter

    def index_all(
        self,
        *,
        embedding_progress: EmbeddingProgress | None = None,
    ) -> dict[str, int]:
        sections = self.documents.all_sections()
        page_texts = _document_texts_by_id(
            sections,
            document_ids=(
                document.document_id for document in self.documents.all_documents()
            ),
        )
        grouped: EntryGroups = {}
        for entry_groups in (
            self._document_entries(sections),
            self._hom_entries(page_texts),
            self._vex_entries(page_texts),
        ):
            for document_id, entries in entry_groups.items():
                grouped.setdefault(document_id, []).extend(entries)

        entries = [entry for group in grouped.values() for entry in group]
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

            for group_entries in grouped.values():
                self.backend.upsert(
                    group_entries,
                    embedding_progress=report_embedding,
                )
        else:
            for group_entries in grouped.values():
                self.backend.upsert(group_entries)

        return {"entries": len(entries)}

    def _document_entries(self, sections: list[DocumentSection]) -> EntryGroups:
        grouped: EntryGroups = {}
        for section in sections:
            namespace = namespace_for_document_kind(section.kind)
            if namespace is None:
                continue
            grouped.setdefault(section.document_id, []).append(
                SearchEntry(
                    id=f"{namespace}:{section.section_id}",
                    namespace=namespace,
                    source_id=section.section_id,
                    content=section.text,
                    content_hash=section.content_hash,
                    embedding_profile=self.embedding_profile,
                    token_count=section.token_count,
                )
            )
        return grouped

    def _hom_entries(self, page_texts: dict[str, str]) -> EntryGroups:
        grouped: EntryGroups = {}
        for record in self.python_documents.all():
            try:
                canonical = normalize_hom_symbol(record.symbol)
            except HouDocsError as exc:
                if exc.error.code != "hom_document_invalid_symbol":
                    raise
                continue
            if canonical.casefold() != record.symbol.casefold():
                continue

            page_text = page_texts.get(record.document_id)
            if page_text is None:
                continue

            text = page_text
            if record.kind in {"method", "function"} and record.member_name:
                block = extract_hom_member(page_text, record.member_name)
                if block is None:
                    continue
                _signature, text = block

            content = _specialized_content(record.symbol, record.signatures, text)
            grouped.setdefault(record.document_id, []).append(
                SearchEntry(
                    id=f"hom:{record.symbol}",
                    namespace=SearchDomain.HOM.value,
                    source_id=record.symbol,
                    content=content,
                    content_hash=_content_hash(content),
                    embedding_profile=self.embedding_profile,
                    token_count=self.token_counter(text),
                )
            )
        return grouped

    def _vex_entries(self, page_texts: dict[str, str]) -> EntryGroups:
        grouped: EntryGroups = {}
        for record in self.vex_documents.all():
            text = page_texts.get(record.document_id)
            if text is None:
                continue
            readable_text = normalize_vex_text(
                text,
                record.function_name,
                record.signatures,
            )
            content = _specialized_content(
                record.function_name,
                record.signatures,
                readable_text,
            )
            grouped.setdefault(record.document_id, []).append(
                SearchEntry(
                    id=f"vex:{record.function_name}",
                    namespace=SearchDomain.VEX.value,
                    source_id=record.function_name,
                    content=content,
                    content_hash=_content_hash(content),
                    embedding_profile=self.embedding_profile,
                    token_count=self.token_counter(readable_text),
                )
            )
        return grouped


def _document_texts_by_id(
    sections: list[DocumentSection],
    *,
    document_ids: Iterable[str],
) -> dict[str, str]:
    grouped: dict[str, list[DocumentSection]] = {
        document_id: [] for document_id in document_ids
    }
    for section in sections:
        grouped.setdefault(section.document_id, []).append(section)
    return {
        document_id: compose_document_text(document_sections)
        for document_id, document_sections in grouped.items()
    }


def _specialized_content(
    symbol: str,
    signatures: tuple[str, ...],
    text: str,
) -> str:
    return "\n".join(part for part in (symbol, *signatures, text) if part).strip()


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
