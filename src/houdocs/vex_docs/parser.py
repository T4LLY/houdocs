from __future__ import annotations

import re
from pathlib import PurePosixPath

from houdocs.docs.header import parse_page_properties
from houdocs.docs.models import Document
from houdocs.vex_docs.models import VexDocumentRecord

_HEADING_RE = re.compile(r"^=\s*(?P<title>.*?)\s*=\s*$")


def parse_vex_document(document: Document, source: str) -> VexDocumentRecord | None:
    properties = parse_page_properties(source)
    if properties.get("type", "").casefold() != "vex":
        return None
    function = _function_name(document, source)
    if not function:
        return None
    return VexDocumentRecord(
        function_name=function,
        document_id=document.document_id,
        signatures=tuple(_vex_signatures(source, function)),
        contexts=_split_values(properties.get("context")),
        group_name=properties.get("group") or None,
        tags=_split_values(properties.get("tags")),
        status=properties.get("status") or None,
        metadata={"reference_type": "vex"},
    )


def _function_name(document: Document, source: str) -> str | None:
    # Real Houdini VEX docs contain a few stale page titles. The filename is
    # the canonical function name for vex/functions/<function>.txt.
    stem = PurePosixPath(document.relative_path).stem
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", stem):
        return stem
    for line in source.splitlines():
        match = _HEADING_RE.match(line.rstrip())
        if match:
            title = match.group("title").strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", title):
                return title
    return None


def _split_values(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item for item in re.split(r"[\s,]+", value.strip()) if item)


def _vex_signatures(source: str, function: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(rf"\b{re.escape(function)}\s*\(")
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
        if len(line) - len(line.lstrip(" ")) > 4:
            continue
        value = normalize_vex_signature(stripped)
        if value is None or not pattern.search(value):
            continue
        if len(value) > 300 or value.endswith((".", ":")):
            continue
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

def normalize_vex_signature(line: str) -> str | None:
    value = line.strip()
    if not value:
        return None
    value = re.sub(r"^:usage:\s*", "", value, flags=re.IGNORECASE)
    value = value.rstrip(":").strip()
    if value.startswith("`") and value.endswith("`") and len(value) >= 2:
        value = value[1:-1].strip()
    value = value.strip("*_ ")
    return value or None


def normalize_vex_text(
    text: str,
    function: str,
    signatures: tuple[str, ...],
) -> str:
    if not text:
        return text
    known = set(signatures)
    output: list[str] = []
    for index, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if index == 0 and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", stripped):
            output.append(function)
            continue
        normalized = normalize_vex_signature(line)
        if normalized in known:
            output.append(normalized)
        else:
            output.append(line)
    return "\n".join(output).strip()
