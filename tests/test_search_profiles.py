from __future__ import annotations

from pathlib import Path

import numpy as np

from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.models import SearchEntry
from houdocs.search.store import initialize_search_database


class FakeEmbeddings:
    def encode(self, texts, profile):
        del profile
        return np.asarray([[float(len(text)), 1.0] for text in texts], dtype=np.float32)


class ProfileDense:
    def __init__(self) -> None:
        self.entries: dict[str, list[str]] = {}

    def upsert(self, profile, entries, vectors_by_hash):
        del vectors_by_hash
        self.entries[profile] = [entry.id for entry in entries]

    def remove(self, profile, entry_ids):
        self.entries[profile] = [
            entry_id
            for entry_id in self.entries.get(profile, [])
            if entry_id not in set(entry_ids)
        ]

    def search(self, profile, query_vector, *, namespaces, top_k):
        del query_vector, namespaces
        return self.entries.get(profile, [])[:top_k]


def test_search_fuses_dense_candidates_from_all_current_profiles(
    tmp_path: Path,
) -> None:
    database = tmp_path / "search.db"
    initialize_search_database(database)
    backend = HybridSearchBackend(
        database=database,
        embeddings=FakeEmbeddings(),
        dense_index=ProfileDense(),
    )
    backend.upsert(
        [SearchEntry("p1-entry", "docs", "p1-source", "alpha one", "hash-1", "p1", 1)]
    )
    backend.upsert(
        [SearchEntry("p2-entry", "docs", "p2-source", "alpha two", "hash-2", "p2", 1)]
    )

    hits = backend.search("alpha", namespaces=["docs"], top_k=2)

    assert {hit.source_id for hit in hits} == {"p1-source", "p2-source"}
