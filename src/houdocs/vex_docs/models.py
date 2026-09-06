from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VexDocumentRecord:
    function_name: str
    document_id: str
    signatures: tuple[str, ...]
    contexts: tuple[str, ...]
    group_name: str | None
    tags: tuple[str, ...]
    status: str | None
    metadata: dict[str, object]
