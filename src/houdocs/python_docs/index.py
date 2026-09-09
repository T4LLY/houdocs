from __future__ import annotations

from pathlib import Path, PurePosixPath

from houdocs.docs.repository import DocumentRepository
from houdocs.specialized_indexing import SpecializedIssueCallback, emit_specialized_issue
from houdocs.python_docs.models import PythonDocumentRecord
from houdocs.python_docs.parser import parse_python_document
from houdocs.python_docs.repository import PythonRepository


class PythonIndexer:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        repository: PythonRepository,
        docs_directory: Path,
    ) -> None:
        self.documents = documents
        self.repository = repository
        self.docs_directory = docs_directory

    def index_all(self, *, on_warning: SpecializedIssueCallback | None = None, on_error: SpecializedIssueCallback | None = None) -> dict[str, int]:
        by_symbol: dict[str, PythonDocumentRecord] = {}
        documents = 0
        failed = 0
        duplicates = 0
        for document in self.documents.all_documents():
            if document.kind != "hom":
                continue
            path = self.docs_directory / PurePosixPath(document.relative_path)
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
                records = parse_python_document(document, source)
            except Exception as exc:
                failed += 1
                emit_specialized_issue(on_error, "python_document_parse_error", f"{type(exc).__name__}: {exc}", document.relative_path, None)
                continue
            if records:
                documents += 1
            for record in records:
                if record.symbol in by_symbol:
                    duplicates += 1
                    emit_specialized_issue(on_warning, "python_symbol_duplicate", "Duplicate Python/HOM symbol; keeping first indexed document.", document.relative_path, record.symbol)
                    continue
                by_symbol[record.symbol] = record
        self.repository.insert_all(list(by_symbol.values()))
        return {"documents": documents, "symbols": len(by_symbol), "duplicates": duplicates, "failed": failed}
