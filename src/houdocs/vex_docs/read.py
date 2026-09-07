from __future__ import annotations

from houdocs.docs.read import DocumentReader
from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.vex_docs.parser import normalize_vex_text
from houdocs.vex_docs.repository import VexRepository


class VexDocumentReader:
    def __init__(self, *, documents: DocumentRepository, repository: VexRepository) -> None:
        self.documents = documents
        self.repository = repository
        self.document_reader = DocumentReader(documents)

    def read(self, function: str) -> dict[str, object]:
        name = function.strip()
        if not name:
            raise HouDocsError("vex_document_not_found", "Provide a VEX function name.")
        record = self.repository.get(name)
        if record is None:
            raise HouDocsError(
                "vex_document_not_found",
                f"VEX documentation not found: {name}",
            )
        document = self.documents.document(record.document_id)
        text = normalize_vex_text(
            str(self.document_reader.page(document)["text"]),
            record.function_name,
            record.signatures,
        )
        return {
            "function": record.function_name,
            "document": document.title,
            "relative_path": document.relative_path,
            "houdini_version": document.houdini_version,
            "signatures": list(record.signatures),
            "contexts": list(record.contexts),
            "group": record.group_name,
            "tags": list(record.tags),
            "status": record.status,
            "text": text,
        }
