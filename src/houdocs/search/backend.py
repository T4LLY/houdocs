from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from houdocs.search.embedding import EmbeddingProvider
from houdocs.search.models import SearchEntry, SearchHit


class SearchBackend(Protocol):
    embeddings: EmbeddingProvider

    def upsert(
        self,
        entries: Sequence[SearchEntry],
        *,
        embedding_progress: Callable[[int, float], None] | None = None,
    ) -> None: ...

    def remove(self, entry_ids: Sequence[str]) -> None: ...

    def entry_ids(self, namespace: str) -> list[str]: ...

    def search(
        self,
        query: str,
        *,
        namespaces: Sequence[str],
        top_k: int,
    ) -> list[SearchHit]: ...
