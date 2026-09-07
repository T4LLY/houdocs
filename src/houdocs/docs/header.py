from __future__ import annotations

import re


_PROPERTY_RE = re.compile(r"^#(?P<name>[A-Za-z0-9_-]+):\s*(?P<value>.*)$")
_HEADING_RE = re.compile(
    r"^(?P<marks>={1,6})\s*.*?\s*(?P=marks)(?:\s*\([^)]+\))?\s*$"
)
_AT_SECTION_RE = re.compile(r"^@[A-Za-z0-9_-]+(?:\s+.*)?$")


def parse_page_properties(source: str) -> dict[str, str]:
    """Read Bookish page properties before the first document section.

    Production Houdini help may put properties before the page title, after the
    page title, or after introductory prose. Section headings and ``@`` blocks
    mark the end of page-level metadata.
    """

    properties: dict[str, str] = {}
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for line in lines:
        stripped = line.strip()
        heading = _HEADING_RE.match(stripped)
        if heading and len(heading.group("marks")) >= 2:
            break
        if _AT_SECTION_RE.match(stripped):
            break

        match = _PROPERTY_RE.match(line.rstrip())
        if match:
            properties[match.group("name")] = match.group("value").strip()
    return properties
