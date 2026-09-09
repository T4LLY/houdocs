from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Document:
    document_id: str
    title: str
    relative_path: str
    kind: str
    houdini_version: str | None


@dataclass(frozen=True)
class DocumentSection:
    section_id: str
    document_id: str
    ordinal: int
    anchor: str | None
    heading: str | None
    heading_path: tuple[str, ...]
    heading_level: int | None
    kind: str
    content_hash: str
    token_count: int
    text: str
