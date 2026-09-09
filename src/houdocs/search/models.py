from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchEntry:
    id: str
    namespace: str
    source_id: str
    content: str
    content_hash: str
    embedding_profile: str
    token_count: int | None = None


@dataclass(frozen=True)
class SearchHit:
    namespace: str
    source_id: str
    score: float
    token_count: int | None = None
