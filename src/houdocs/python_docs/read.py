from __future__ import annotations

import re

from houdocs.docs.read import DocumentReader
from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.python_docs.repository import PythonRepository


_PYTHON_SIGNATURE_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*(?:[-=]*>|→)?.*$"
)


class PythonDocumentReader:
    def __init__(self, *, documents: DocumentRepository, repository: PythonRepository) -> None:
        self.documents = documents
        self.repository = repository
        self.document_reader = DocumentReader(documents)

    def read(self, symbol: str) -> dict[str, object]:
        canonical = _normalize_symbol(symbol)
        record = self.repository.get(canonical)
        if record is None:
            raise HouDocsError(
                "python_document_not_found",
                f"Python/HOM documentation not found: {canonical}",
            )
        document = self.documents.document(record.document_id)
        page_text = str(self.document_reader.page(document)["text"])
        text = page_text
        if record.kind in {"method", "function"} and record.member_name:
            block = _extract_python_member(page_text, record.member_name)
            if block is None:
                raise HouDocsError(
                    "python_document_member_not_found",
                    f"Python/HOM member not found in {document.title}: {record.member_name}",
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


def _normalize_symbol(symbol: str) -> str:
    value = symbol.strip().replace("#", ".")
    if value.endswith("()"):
        value = value[:-2]
    value = value.strip(".")
    if not value or any(not part for part in value.split(".")):
        raise HouDocsError("python_document_invalid_symbol", "Provide a Python/HOM symbol name.")
    return value


def _extract_python_member(text: str, member: str) -> tuple[str, str] | None:
    lines = text.splitlines()
    start: int | None = None
    signature: str | None = None
    for index, line in enumerate(lines):
        parsed = _python_signature(line)
        if parsed is not None and parsed[0] == member:
            start = index
            signature = parsed[1]
            break
    if start is None or signature is None:
        return None

    end = len(lines)
    for index in range(start + 1, len(lines)):
        parsed = _python_signature(lines[index])
        if parsed is not None and parsed[0] != member:
            end = index
            break
    block = "\n".join(lines[start:end]).strip()
    return signature, block


def _python_signature(line: str) -> tuple[str, str] | None:
    if len(line) - len(line.lstrip(" ")) > 4:
        return None
    value = line.strip()
    if not value or value.startswith((">>>", "...")):
        return None
    value = re.sub(r"^:[A-Za-z0-9_-]+:\s*", "", value)
    value = value.strip("`*_ ")
    match = _PYTHON_SIGNATURE_RE.match(value)
    if match is None:
        return None
    name = match.group("name")
    signature = value.rstrip(":").strip()
    return name, signature
