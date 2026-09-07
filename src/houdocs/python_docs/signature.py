from __future__ import annotations

import re


_PYTHON_SIGNATURE_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*(?:[-=]*>|→)?.*$"
)


def parse_python_signature(line: str) -> tuple[str, str] | None:
    if len(line) - len(line.lstrip(" ")) > 4:
        return None
    value = line.strip()
    if not value or value.startswith((">>>", "...")):
        return None

    if value.startswith("::"):
        value = value[2:].lstrip()
        if value.startswith("`"):
            closing = value.find("`", 1)
            if closing > 0:
                value = value[1:closing] + value[closing + 1 :]

    value = re.sub(r"^:[A-Za-z0-9_-]+:\s*", "", value)
    value = value.strip("`*_ ")
    match = _PYTHON_SIGNATURE_RE.match(value)
    if match is None:
        return None
    return match.group("name"), value.rstrip(":").strip()
