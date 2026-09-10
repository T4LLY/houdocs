from __future__ import annotations

from houdocs.docs.read import DocumentReader
from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.python_docs.repository import PythonRepository
from houdocs.python_docs.text import extract_hom_member, normalize_hom_symbol


class PythonDocumentReader:
    def __init__(self, *, documents: DocumentRepository, repository: PythonRepository) -> None:
        self.documents = documents
        self.repository = repository
        self.document_reader = DocumentReader(documents)

    def read(self, symbol: str) -> dict[str, object]:
        canonical = normalize_hom_symbol(symbol)
        record = self.repository.get(canonical)
        if record is None:
            raise HouDocsError(
                "hom_document_not_found",
                f"HOM documentation not found: {canonical}",
            )
        document = self.documents.document(record.document_id)
        page_text = str(self.document_reader.page(document)["text"])
        text = page_text
        if record.kind in {"method", "function"} and record.member_name:
            block = extract_hom_member(page_text, record.member_name)
            if block is None:
                raise HouDocsError(
                    "hom_document_member_not_found",
                    f"HOM member not found in {document.title}: {record.member_name}",
                )
            _signature, text = block
        return {
            "symbol": record.symbol,
            "document": document.title,
            "relative_path": document.relative_path,
            "houdini_version": document.houdini_version,
            "kind": record.kind,
            "parent_symbol": record.parent_symbol,
            "member_name": record.member_name,
            "signatures": list(record.signatures),
            "text": text,
        }
