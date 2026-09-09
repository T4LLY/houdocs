from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PythonDocumentRecord:
    symbol: str
    document_id: str
    parent_symbol: str | None
    member_name: str | None
    kind: str
    signatures: tuple[str, ...]
