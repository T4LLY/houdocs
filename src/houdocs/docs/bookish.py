from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, replace

from houdocs.docs.models import DocumentSection


_HEADING_RE = re.compile(
    r"^(?P<marks>={1,6})\s*(?P<title>.*?)\s*(?P=marks)(?:\s*\((?P<anchor>[^)]+)\))?\s*$"
)
_PROPERTY_RE = re.compile(r"^#(?P<name>[A-Za-z0-9_-]+):\s*(?P<value>.*)$")
_AT_SECTION_RE = re.compile(r"^@(?P<name>[A-Za-z0-9_-]+)(?:\s+(?P<title>.+))?\s*$")
_LINK_RE = re.compile(r"\[([^\[\]|]+)\|[^\]]+\]")
_IMAGE_RE = re.compile(r"^\s*\[Image:[^\]]+\]\s*$", re.IGNORECASE)
_AT_SECTIONS = {
    "actions",
    "attributes",
    "examples",
    "globals",
    "glossary",
    "inputs",
    "options",
    "parameters",
    "related",
    "subtopics",
    "suite",
    "usage",
}


@dataclass
class _SectionBuilder:
    heading: str | None
    heading_path: tuple[str, ...]
    level: int | None
    anchor: str | None
    ordinal: int
    parts: list[str]


class BookishDocumentParser:
    """Extract semantic sections from Houdini Bookish wiki source."""

    def parse(
        self,
        source: str,
        *,
        document_id: str,
        kind: str,
    ) -> list[DocumentSection]:
        lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        page_properties = self._page_properties(lines)
        heading_stack: list[str | None] = [None] * 6
        current: _SectionBuilder | None = None
        sections: list[DocumentSection] = []
        used_section_ids: set[str] = set()
        ordinal = 0
        page_title: str | None = None
        in_code_block = False

        def finish(builder: _SectionBuilder | None) -> None:
            if builder is None:
                return
            body = self._normalize_body(builder.parts)
            context = [part for part in (page_title, *builder.heading_path[1:]) if part]
            if builder.level == 1 and page_title:
                context = [page_title]
            text_parts = [*context]
            if body:
                text_parts.append(body)
            text = "\n".join(self._dedupe_adjacent(text_parts)).strip()
            if not text:
                return
            section = self._make_section(
                document_id=document_id,
                kind=kind,
                builder=builder,
                text=text,
                page_properties=page_properties,
            )
            base_id = section.section_id
            if base_id in used_section_ids:
                suffix = 2
                while f"{base_id}-{suffix}" in used_section_ids:
                    suffix += 1
                section = replace(section, section_id=f"{base_id}-{suffix}")
            used_section_ids.add(section.section_id)
            sections.append(section)

        for raw_line in lines:
            line = raw_line.rstrip()
            stripped = line.strip()
            if in_code_block:
                if current is not None:
                    current.parts.append(line)
                if stripped == "}}}":
                    in_code_block = False
                continue
            if stripped == "{{{":
                if current is None:
                    ordinal += 1
                    current = _SectionBuilder(
                        heading=page_title,
                        heading_path=(page_title,) if page_title else (),
                        level=1 if page_title else None,
                        anchor=None,
                        ordinal=ordinal,
                        parts=[],
                    )
                current.parts.append(line)
                in_code_block = True
                continue

            heading_match = _HEADING_RE.match(line)
            if heading_match:
                finish(current)
                ordinal += 1
                level = len(heading_match.group("marks"))
                heading = heading_match.group("title").strip() or None
                if level == 1 and heading:
                    page_title = heading
                heading_stack[level - 1] = heading
                for index in range(level, 6):
                    heading_stack[index] = None
                current = _SectionBuilder(
                    heading=heading,
                    heading_path=tuple(part for part in heading_stack[:level] if part),
                    level=level,
                    anchor=(heading_match.group("anchor") or None),
                    ordinal=ordinal,
                    parts=[],
                )
                continue

            at_match = _AT_SECTION_RE.match(line)
            if at_match and at_match.group("name").casefold() in _AT_SECTIONS:
                finish(current)
                ordinal += 1
                name = at_match.group("name").casefold()
                heading = (
                    at_match.group("title") or name.replace("_", " ").title()
                ).strip()
                heading_stack[1] = heading
                for index in range(2, 6):
                    heading_stack[index] = None
                current = _SectionBuilder(
                    heading=heading,
                    heading_path=tuple(part for part in heading_stack[:2] if part),
                    level=2,
                    anchor=name,
                    ordinal=ordinal,
                    parts=[],
                )
                continue

            property_match = _PROPERTY_RE.match(line)
            if (
                property_match
                and property_match.group("name") == "id"
                and current is not None
                and not current.parts
            ):
                current.anchor = property_match.group("value").strip() or current.anchor
                continue

            if current is None:
                if line.strip():
                    ordinal += 1
                    current = _SectionBuilder(
                        heading=page_title,
                        heading_path=(page_title,) if page_title else (),
                        level=1 if page_title else None,
                        anchor=None,
                        ordinal=ordinal,
                        parts=[line],
                    )
                continue
            current.parts.append(line)

        finish(current)
        return sections

    def _make_section(
        self,
        *,
        document_id: str,
        kind: str,
        builder: _SectionBuilder,
        text: str,
        page_properties: dict[str, str],
    ) -> DocumentSection:
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        anchor = builder.anchor.strip() if builder.anchor else None
        if anchor:
            section_id = f"{document_id}#{anchor}"
        else:
            synthetic = hashlib.sha256(
                ("/".join(builder.heading_path) + f"|{builder.ordinal}").encode("utf-8")
            ).hexdigest()[:16]
            section_id = f"{document_id}#synthetic-{synthetic}"
        return DocumentSection(
            section_id=section_id,
            document_id=document_id,
            ordinal=builder.ordinal,
            anchor=anchor,
            heading=builder.heading,
            heading_path=builder.heading_path,
            heading_level=builder.level,
            kind=kind,
            content_hash=content_hash,
            token_count=_estimate_tokens(text),
            text=text,
            metadata={"bookish": dict(page_properties)},
        )

    @staticmethod
    def _page_properties(lines: list[str]) -> dict[str, str]:
        properties: dict[str, str] = {}
        for line in lines:
            heading_match = _HEADING_RE.match(line.rstrip())
            if heading_match:
                break
            at_match = _AT_SECTION_RE.match(line.rstrip())
            if at_match and at_match.group("name").casefold() in _AT_SECTIONS:
                break
            match = _PROPERTY_RE.match(line.rstrip())
            if match and match.group("name") != "id":
                properties[match.group("name")] = match.group("value").strip()
        return properties

    @staticmethod
    def _normalize_body(lines: list[str]) -> str:
        output: list[str] = []
        in_code = False
        for raw_line in lines:
            stripped = raw_line.strip()
            if stripped == "{{{":
                in_code = True
                continue
            if stripped == "}}}":
                in_code = False
                continue
            if in_code and stripped.startswith("#!"):
                continue
            if not in_code and _PROPERTY_RE.match(stripped):
                continue
            if _IMAGE_RE.match(raw_line):
                continue
            line = raw_line.replace('"""', "")
            line = _LINK_RE.sub(r"\1", line)
            output.append(line.rstrip())
        text = "\n".join(output).strip()
        return re.sub(r"\n{3,}", "\n\n", text)

    @staticmethod
    def _dedupe_adjacent(parts: list[str]) -> list[str]:
        output: list[str] = []
        for part in parts:
            if not part or (output and output[-1] == part):
                continue
            output.append(part)
        return output


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text.encode("utf-8")) / 3))
