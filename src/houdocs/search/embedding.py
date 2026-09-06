from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Protocol

import numpy as np

from houdocs.errors import HouDocsError


class EmbeddingProvider(Protocol):
    def encode(self, texts: Sequence[str], profile: str) -> np.ndarray: ...


class Model2VecEmbeddingProvider:
    def __init__(self) -> None:
        self._models: dict[str, object] = {}

    def encode(self, texts: Sequence[str], profile: str) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        model = self._models.get(profile)
        if model is None:
            try:
                os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                from huggingface_hub.utils import disable_progress_bars
                from model2vec import StaticModel

                with disable_progress_bars():
                    model = StaticModel.from_pretrained(profile)
            except Exception as exc:
                raise HouDocsError(
                    "embedding_model_load_failed",
                    f"Unable to load embedding profile: {profile}",
                    detail=str(exc),
                ) from exc
            self._models[profile] = model
        try:
            vectors = model.encode(list(texts))
        except Exception as exc:
            raise HouDocsError(
                "embedding_failed",
                f"Embedding failed for profile: {profile}",
                detail=str(exc),
            ) from exc
        array = np.asarray(vectors, dtype=np.float32)
        if array.ndim == 1:
            array = array[None, :]
        return array
