from __future__ import annotations

import re
from pathlib import PurePosixPath

from houdocs.docs.header import parse_page_properties
from houdocs.docs.models import Document
from houdocs.python_docs.models import PythonDocumentRecord
from houdocs.python_docs.signature import parse_python_signature

_HEADING_RE = re.compile(r"^=\s*(?P<title>.*?)\s*=\s*$")


def parse_python_document(
    document: Document, source: str
) -> list[PythonDocumentRecord]:
    properties = parse_page_properties(source)
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
                )
            )
    return records


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
    in_code = False
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("{{{"):
            in_code = True
            continue
        if stripped.startswith("}}}"):
            in_code = False
            continue
        if in_code:
            continue
        parsed = parse_python_signature(line)
        if parsed is None:
            continue
        name, signature = parsed
        if signature in seen.setdefault(name, set()):
            continue
        seen[name].add(signature)
        grouped.setdefault(name, []).append(signature)
    return grouped
