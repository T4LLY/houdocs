from __future__ import annotations

from enum import Enum


class SearchDomain(str, Enum):
    NODE = "node"
    VEX = "vex"
    HOM = "hom"
    DOCUMENT = "document"


ALL_SEARCH_NAMESPACES = tuple(domain.value for domain in SearchDomain)


def namespace_for_document_kind(kind: str) -> str | None:
    normalized = kind.casefold()
    if normalized == "node-doc":
        return SearchDomain.NODE.value
    if normalized in {"hom", "vex"}:
        return None
    return SearchDomain.DOCUMENT.value
