from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

from houdocs.docs.repository import DocumentRepository
from houdocs.python_docs.models import PythonDocumentRecord
from houdocs.python_docs.parser import parse_python_document
from houdocs.python_docs.repository import PythonRepository

IssueCallback = Callable[[str, str, str | None, str | None], None]


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

    def index_all(self, *, on_warning: IssueCallback | None = None, on_error: IssueCallback | None = None) -> dict[str, int]:
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
                _issue(on_error, "python_document_parse_error", f"{type(exc).__name__}: {exc}", document.relative_path, None)
                continue
            if records:
                documents += 1
            for record in records:
                if record.symbol in by_symbol:
                    duplicates += 1
                    _issue(on_warning, "python_symbol_duplicate", "Duplicate Python/HOM symbol; keeping first indexed document.", document.relative_path, record.symbol)
                    continue
                by_symbol[record.symbol] = record
        self.repository.replace_all(list(by_symbol.values()))
        return {"documents": documents, "symbols": len(by_symbol), "duplicates": duplicates, "failed": failed}


def _issue(callback: IssueCallback | None, kind: str, detail: str, document: str | None, symbol: str | None) -> None:
    if callback is not None:
        callback(kind, detail, document, symbol)
