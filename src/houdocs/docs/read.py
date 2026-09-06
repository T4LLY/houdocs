from __future__ import annotations

import json

from houdocs.docs.models import Document, DocumentSection
from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError


class DocumentReader:
    def __init__(self, repository: DocumentRepository) -> None:
        self.repository = repository

    def read(self, page: str, section: str | None = None) -> dict[str, object]:
        document = self._resolve_document(page)
        if section is not None:
            return self.section_for(document, section)
        return self.page(document)

    def page(self, document: Document) -> dict[str, object]:
        sections = self.repository.sections_for_document(document.document_id)
        return {
            **self._document_contract(document),
            "section": None,
            "text": "\n\n".join(item.text for item in sections if item.text).strip(),
        }

    def section_for(self, document: Document, section_name: str) -> dict[str, object]:
        matches = self.repository.sections_matching(document.document_id, section_name)
        if not matches:
            raise HouDocsError(
                "document_section_not_found",
                f"Section not found in {document.title}: {section_name}",
            )
        if len(matches) > 1:
            raise HouDocsError(
                "document_section_ambiguous",
                f"Section name is ambiguous in {document.title}: {section_name}",
                detail=json.dumps(
                    [self._section_contract(item) for item in matches],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        selected = matches[0]
        return {
            **self._document_contract(document),
            "section": self._section_contract(selected),
            "text": selected.text,
        }

    def _resolve_document(self, page: str) -> Document:
        matches = self.repository.documents_for_title(page)
        if not matches:
            raise HouDocsError("document_not_found", f"Document not found: {page}")
        if len(matches) > 1:
            raise HouDocsError(
                "document_ambiguous",
                f"Document title is ambiguous: {page}",
                detail=json.dumps(
                    [
                        {
                            "title": item.title,
                            "relative_path": item.relative_path,
                            "kind": item.kind,
                        }
                        for item in matches
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        return matches[0]

    @staticmethod
    def _document_contract(document: Document) -> dict[str, object]:
        return {
            "document": document.title,
            "relative_path": document.relative_path,
            "kind": document.kind,
            "houdini_version": document.houdini_version,
        }

    @staticmethod
    def _section_contract(section: DocumentSection) -> dict[str, object]:
        return {
            "section_id": section.section_id,
            "ordinal": section.ordinal,
            "heading": section.heading,
            "heading_path": list(section.heading_path),
            "level": section.heading_level,
            "anchor": section.anchor,
        }
