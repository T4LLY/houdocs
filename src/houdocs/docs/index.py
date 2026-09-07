from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from houdocs.docs.bookish import BookishDocumentParser
from houdocs.docs.models import Document, DocumentSection
from houdocs.docs.repository import DocumentRepository
from houdocs.docs.source import CachedDocument, cache_bookish_trees


IssueCallback = Callable[[str, str, str | None], None]
ProgressCallback = Callable[[int, int], None]
TokenCounter = Callable[[str], int]


def _document_id(relative_path: str) -> str:
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:32]


def classify_document(relative_path: str) -> str:
    path = "/" + relative_path.casefold().replace("\\", "/")
    if "/hom/" in path or "/python/" in path:
        return "hom"
    if "/vex/" in path:
        return "vex"
    if "/examples/" in path or "/example/" in path:
        return "example"
    if "/nodes/" in path:
        return "node-doc"
    return "concept"


class DocumentIndexer:
    def __init__(
        self,
        *,
        repository: DocumentRepository,
        parser: BookishDocumentParser,
        cache_directory: Path,
        token_counter: TokenCounter,
    ) -> None:
        self.repository = repository
        self.parser = parser
        self.cache_directory = cache_directory
        self.token_counter = token_counter

    def index_all(
        self,
        sources: Path | Sequence[Path],
        *,
        houdini_version: str | None = None,
        on_error: IssueCallback | None = None,
        progress: ProgressCallback | None = None,
    ) -> dict[str, int]:
        source_roots = (sources,) if isinstance(sources, Path) else tuple(sources)
        cached = cache_bookish_trees(
            source_roots,
            self.cache_directory,
            on_error=on_error,
        )
        current_paths = {item.relative_path for item in cached}
        removed = self._remove_stale_documents(current_paths)
        indexed = 0
        skipped = 0
        failed = 0
        total = len(cached)
        if progress is not None:
            progress(0, total)

        for position, item in enumerate(cached, start=1):
            existing = self.repository.document_for_path(item.relative_path)
            if self._is_current_document(existing, item):
                skipped += 1
                if progress is not None:
                    progress(position, total)
                continue

            document_id = existing.document_id if existing else _document_id(item.relative_path)
            kind = classify_document(item.relative_path)
            try:
                sections = self._parse_sections(item, document_id, kind)
            except Exception as exc:
                failed += 1
                if existing is not None:
                    self.repository.delete_document(existing.document_id)
                if on_error is not None:
                    on_error(
                        "bookish_parse_error",
                        f"{type(exc).__name__}: {exc}",
                        item.relative_path,
                    )
                if progress is not None:
                    progress(position, total)
                continue

            document = Document(
                document_id=document_id,
                title=self._document_title(item, sections),
                relative_path=item.relative_path,
                kind=kind,
                houdini_version=houdini_version,
                content_hash=item.content_hash,
            )
            self.repository.replace_document(document, sections)
            indexed += 1
            if progress is not None:
                progress(position, total)

        return {
            "total": len(cached),
            "indexed": indexed,
            "skipped": skipped,
            "removed": removed,
            "failed": failed,
        }

    def _is_current_document(
        self,
        existing: Document | None,
        item: CachedDocument,
    ) -> bool:
        if existing is None or existing.content_hash != item.content_hash:
            return False
        return bool(self.repository.section_ids_for_document(existing.document_id))

    def _remove_stale_documents(self, current_paths: set[str]) -> int:
        removed = 0
        for existing in self.repository.all_documents():
            if existing.relative_path in current_paths:
                continue
            self.repository.delete_document(existing.document_id)
            removed += 1
        return removed

    def _parse_sections(
        self,
        item: CachedDocument,
        document_id: str,
        kind: str,
    ) -> list[DocumentSection]:
        source_text = item.cached_path.read_text(encoding="utf-8", errors="replace")
        sections = self.parser.parse(
            source_text,
            document_id=document_id,
            kind=kind,
        )
        return [
            self._with_metadata(
                replace(section, token_count=self.token_counter(section.text)),
                item.relative_path,
            )
            for section in sections
        ]

    @staticmethod
    def _with_metadata(
        section: DocumentSection,
        relative_path: str,
    ) -> DocumentSection:
        metadata = {
            **section.metadata,
            "kind": section.kind,
            "document_id": section.document_id,
            "relative_path": relative_path,
            "ordinal": section.ordinal,
            "anchor": section.anchor,
            "heading": section.heading,
            "heading_path": list(section.heading_path),
            "heading_level": section.heading_level,
        }
        return DocumentSection(
            section_id=section.section_id,
            document_id=section.document_id,
            ordinal=section.ordinal,
            anchor=section.anchor,
            heading=section.heading,
            heading_path=section.heading_path,
            heading_level=section.heading_level,
            kind=section.kind,
            content_hash=section.content_hash,
            token_count=section.token_count,
            text=section.text,
            metadata=metadata,
        )

    @staticmethod
    def _document_title(
        item: CachedDocument,
        sections: list[DocumentSection],
    ) -> str:
        for section in sections:
            if section.heading_path:
                return section.heading_path[0]
        return Path(item.relative_path).stem
