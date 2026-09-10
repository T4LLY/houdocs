from __future__ import annotations

from collections.abc import Iterable

from houdocs.docs.models import DocumentSection


def compose_document_text(sections: Iterable[DocumentSection]) -> str:
    return "\n\n".join(section.text for section in sections if section.text).strip()
