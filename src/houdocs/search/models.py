from __future__ import annotations

from dataclasses import dataclass, field

from houdocs.search.rrf import normalize_rrf_score


@dataclass(frozen=True)
class SearchEntry:
    id: str
    namespace: str
    source_id: str
    content: str
    content_hash: str
    embedding_profile: str
    token_count: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchHit:
    id: str
    namespace: str
    source_id: str
    score: float
    metadata: dict[str, object]
    token_count: int | None = None
    lexical_rank: int | None = None
    dense_rank: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "namespace": self.namespace,
            "source_id": self.source_id,
            "score": normalize_rrf_score(self.score),
            "metadata": self.metadata,
            "token_count": self.token_count,
            "lexical_rank": self.lexical_rank,
            "dense_rank": self.dense_rank,
        }
