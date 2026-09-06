from __future__ import annotations

from collections.abc import Sequence


_PUBLIC_SCORE_SCALE = 10_000
_PUBLIC_SCORE_DECIMALS = 6


def normalize_rrf_score(score: float) -> float:
    return round(score * _PUBLIC_SCORE_SCALE, _PUBLIC_SCORE_DECIMALS)


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    *,
    k: int,
    weights: Sequence[float] | None = None,
) -> dict[str, float]:
    if k < 0:
        raise ValueError("k must be >= 0")
    if weights is None:
        weights = [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError("weights must match rankings")

    scores: dict[str, float] = {}
    for ranking, weight in zip(rankings, weights):
        for rank, entry_id in enumerate(ranking, start=1):
            scores[entry_id] = scores.get(entry_id, 0.0) + weight / (k + rank)
    return scores
