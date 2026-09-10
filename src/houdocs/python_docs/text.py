from __future__ import annotations

from houdocs.errors import HouDocsError
from houdocs.python_docs.signature import parse_python_signature


def normalize_hom_symbol(symbol: str) -> str:
    value = symbol.strip().replace("#", ".")
    if value.endswith("()"):
        value = value[:-2]
    value = value.strip(".")
    if not value or any(not part for part in value.split(".")):
        raise HouDocsError("hom_document_invalid_symbol", "Provide a HOM symbol name.")
    return value


def extract_hom_member(text: str, member: str) -> tuple[str, str] | None:
    lines = text.splitlines()
    start: int | None = None
    signature: str | None = None
    for index, line in enumerate(lines):
        parsed = parse_python_signature(line)
        if parsed is not None and parsed[0] == member:
            start = index
            signature = parsed[1]
            break
    if start is None or signature is None:
        return None

    end = len(lines)
    for index in range(start + 1, len(lines)):
        parsed = parse_python_signature(lines[index])
        if parsed is not None and parsed[0] != member:
            end = index
            break
    block_lines: list[str] = []
    for line in lines[start:end]:
        parsed = parse_python_signature(line)
        if parsed is not None and parsed[0] == member:
            block_lines.append(parsed[1])
        else:
            block_lines.append(line)
    block = "\n".join(block_lines).strip()
    return signature, block
