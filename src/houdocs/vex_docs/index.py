from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

from houdocs.docs.repository import DocumentRepository
from houdocs.vex_docs.models import VexDocumentRecord
from houdocs.vex_docs.parser import parse_vex_document
from houdocs.vex_docs.repository import VexRepository

IssueCallback = Callable[[str, str, str | None, str | None], None]


class VexIndexer:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        repository: VexRepository,
        docs_directory: Path,
    ) -> None:
        self.documents = documents
        self.repository = repository
        self.docs_directory = docs_directory

    def index_all(self, *, on_warning: IssueCallback | None = None, on_error: IssueCallback | None = None) -> dict[str, int]:
        by_function: dict[str, VexDocumentRecord] = {}
        documents = 0
        failed = 0
        duplicates = 0
        for document in self.documents.all_documents():
            if document.kind != "vex":
                continue
            path = self.docs_directory / PurePosixPath(document.relative_path)
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
                record = parse_vex_document(document, source)
            except Exception as exc:
                failed += 1
                _issue(on_error, "vex_document_parse_error", f"{type(exc).__name__}: {exc}", document.relative_path, None)
                continue
            if record is None:
                continue
            documents += 1
            if record.function_name in by_function:
                duplicates += 1
                _issue(on_warning, "vex_function_duplicate", "Duplicate VEX function; keeping first indexed document.", document.relative_path, record.function_name)
                continue
            by_function[record.function_name] = record
        self.repository.replace_all(list(by_function.values()))
        return {"documents": documents, "functions": len(by_function), "duplicates": duplicates, "failed": failed}


def _issue(callback: IssueCallback | None, kind: str, detail: str, document: str | None, symbol: str | None) -> None:
    if callback is not None:
        callback(kind, detail, document, symbol)
