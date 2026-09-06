from __future__ import annotations

import re
from pathlib import PurePosixPath

from houdocs.docs.models import Document
from houdocs.python_docs.models import PythonDocumentRecord

_PROPERTY_RE = re.compile(r"^#(?P<name>[A-Za-z0-9_-]+):\s*(?P<value>.*)$")
_HEADING_RE = re.compile(r"^=\s*(?P<title>.*?)\s*=\s*$")
_PYTHON_SIGNATURE_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*(?:[-=]*>|→)?.*$"
)


def parse_python_document(document: Document, source: str) -> list[PythonDocumentRecord]:
    properties = _page_properties(source)
    reference_type = properties.get("type", "").casefold()
    if reference_type not in {"homclass", "homfunction", "hommodule"}:
        return []

    symbol = _page_symbol(document, source)
    if not symbol:
        return []
    grouped = _group_signatures(source)
    records: list[PythonDocumentRecord] = []

    if reference_type == "homclass":
        kind = "class"
    elif reference_type == "hommodule":
        kind = "module"
    else:
        kind = "function"

    own_name = symbol.rsplit(".", 1)[-1]
    own_signatures = tuple(grouped.get(own_name, ())) if kind == "function" else ()
    records.append(
        PythonDocumentRecord(
            symbol=symbol,
            document_id=document.document_id,
            parent_symbol=symbol.rpartition(".")[0] or None,
            member_name=own_name,
            kind=kind,
            signatures=own_signatures,
            metadata={"reference_type": reference_type},
        )
    )

    if kind in {"class", "module"}:
        member_kind = "method" if kind == "class" else "function"
        for member_name, signatures in grouped.items():
            records.append(
                PythonDocumentRecord(
                    symbol=f"{symbol}.{member_name}",
                    document_id=document.document_id,
                    parent_symbol=symbol,
                    member_name=member_name,
                    kind=member_kind,
                    signatures=tuple(signatures),
                    metadata={"reference_type": reference_type},
                )
            )
    return records


def _page_properties(source: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in source.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.lstrip().startswith("=") or line.startswith("@"):
            break
        match = _PROPERTY_RE.match(line.rstrip())
        if match:
            properties[match.group("name")] = match.group("value").strip()
    return properties


def _page_symbol(document: Document, source: str) -> str | None:
    for line in source.splitlines():
        match = _HEADING_RE.match(line.rstrip())
        if match:
            title = match.group("title").strip()
            if title:
                return title
    path = PurePosixPath(document.relative_path)
    parts = list(path.with_suffix("").parts)
    if parts and parts[0].casefold() in {"hom", "python"}:
        parts = parts[1:]
    if parts and parts[-1] == "index":
        parts.pop()
    if parts:
        parts[-1] = parts[-1].removesuffix("_")
    return ".".join(parts) or None


def _group_signatures(source: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for line in source.splitlines():
        parsed = _python_signature(line)
        if parsed is None:
            continue
        name, signature = parsed
        if signature in seen.setdefault(name, set()):
            continue
        seen[name].add(signature)
        grouped.setdefault(name, []).append(signature)
    return grouped


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
    return match.group("name"), value.rstrip(":").strip()
