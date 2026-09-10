from __future__ import annotations

from houdocs.docs.models import Document, DocumentSection
from houdocs.docs.repository import DocumentRepository
from houdocs.docs.text import compose_document_text
from houdocs.errors import HouDocsError


class DocumentReader:
    def __init__(self, repository: DocumentRepository) -> None:
        self.repository = repository

    def read(
        self,
        page: str,
        section: str | None = None,
        *,
        pick: int | None = None,
    ) -> dict[str, object]:
        document = self._resolve_document(page, pick=pick)
        if section is not None:
            return self.section_for(document, section)
        return self.page(document)

    def page(self, document: Document) -> dict[str, object]:
        sections = self.repository.sections_for_document(document.document_id)
        return {"text": compose_document_text(sections)}

    def sections(self, page: str, *, pick: int | None = None) -> dict[str, object]:
        document = self._resolve_document(page, pick=pick)
        return {
            "sections": [
                {
                    "path": self._section_path(section),
                    "tokens": section.token_count,
                }
                for section in self.repository.sections_for_document(
                    document.document_id
                )
            ]
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
                choices=[self._section_choice(item) for item in matches],
            )
        return {"text": matches[0].text}

    def _resolve_document(self, page: str, *, pick: int | None = None) -> Document:
        matches = self.repository.documents_for_title(page)
        if not matches:
            raise HouDocsError("document_not_found", f"Document not found: {page}")
        if pick is not None:
            if pick < 1 or pick > len(matches):
                raise HouDocsError(
                    "document_pick_out_of_range",
                    f"Document pick is out of range for {page}: {pick} (1-{len(matches)})",
                )
            return matches[pick - 1]
        if len(matches) > 1:
            raise HouDocsError(
                "document_ambiguous",
                f"Document title is ambiguous: {page}. Re-run with --pick N.",
                choices=[self._choice_label(item) for item in matches],
            )
        return matches[0]

    @staticmethod
    def _choice_label(document: Document) -> str:
        parts = [
            part
            for part in document.relative_path.replace("\\", "/").split("/")
            if part
        ]
        if len(parts) >= 2 and parts[0].casefold() == "nodes":
            domain = parts[1].upper()
        elif parts:
            domain = parts[0].replace("_", " ").replace("-", " ").title()
        else:
            domain = document.kind
        return f"{domain} / {document.title}"

    @staticmethod
    def _section_choice(section: DocumentSection) -> str:
        return "/".join(DocumentReader._section_path(section))

    @staticmethod
    def _section_path(section: DocumentSection) -> list[str]:
        parts = list(section.heading_path)
        if len(parts) > 1:
            parts = parts[1:]
        if parts:
            return parts
        if section.heading:
            return [section.heading]
        if section.anchor:
            return [f"#{section.anchor}"]
        return [f"section {section.ordinal + 1}"]
