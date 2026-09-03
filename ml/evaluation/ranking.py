from __future__ import annotations

from collections import Counter
from itertools import combinations
from math import log2

import numpy as np

from recommendation.baselines.popularity import PopularityBaseline
from recommendation.ranking.current_catalog import RankedMovie


def _genre_diversity(recommendations: list[RankedMovie]) -> float | None:
    distances: list[float] = []
    for left, right in combinations(recommendations, 2):
        left_genres = set(left.genres)
        right_genres = set(right.genres)
        union = left_genres.union(right_genres)
        if union:
            distances.append(1.0 - len(left_genres.intersection(right_genres)) / len(union))
    return float(np.mean(distances)) if distances else None


def _genre_entropy(recommendations: list[RankedMovie]) -> float | None:
    counts = Counter(genre for item in recommendations for genre in set(item.genres))
    if len(counts) < 2:
        return 0.0 if counts else None
    total = sum(counts.values())
    entropy = -sum((count / total) * log2(count / total) for count in counts.values())
    return entropy / log2(len(counts))


def compute_ranking_metrics(
    recommendations: list[RankedMovie],
    *,
    candidates_considered: int,
    popularity: PopularityBaseline,
    total_users: int,
) -> dict[str, object]:
    linked = [item for item in recommendations if item.movielens_id is not None]
    counts: list[int] = []
    novelty: list[float] = []
    for item in linked:
        position = int(np.searchsorted(popularity.movie_ids, item.movielens_id))
        if position >= len(popularity.movie_ids):
            continue
        support = int(popularity.counts[position])
        counts.append(support)
        novelty.append(-log2((support + 1) / (total_users + 1)))
    years = [item.year for item in recommendations if item.year is not None]
    genres = {genre for item in recommendations for genre in item.genres}
    primary_genres = {item.genres[0] for item in recommendations if item.genres}
    modes = Counter(item.score_mode for item in recommendations)
    origins = Counter(item.candidate_origin for item in recommendations)
    scores = [item.score for item in recommendations]
    returned = len(recommendations)
    return {
        "coverage": {
            "recommendations_returned": returned,
            "candidates_considered": candidates_considered,
            "selection_rate": returned / candidates_considered
            if candidates_considered
            else 0.0,
            "movielens_evidence": len(linked),
            "cold_start": modes.get("cold_start", 0),
            "score_modes": dict(modes),
            "candidate_origins": dict(origins),
        },
        "diversity": {
            "unique_genres": len(genres),
            "unique_primary_genres": len(primary_genres),
            "intra_list_genre_diversity": _genre_diversity(recommendations),
            "normalized_genre_entropy": _genre_entropy(recommendations),
            "minimum_year": min(years) if years else None,
            "maximum_year": max(years) if years else None,
            "distinct_decades": len({year // 10 * 10 for year in years}),
        },
        "novelty": {
            "movielens_items_measured": len(novelty),
            "mean_self_information_bits": float(np.mean(novelty)) if novelty else None,
            "median_rating_support": float(np.median(counts)) if counts else None,
            "cold_start_novelty_unavailable": returned - len(novelty),
        },
        "scores": {
            "minimum": min(scores) if scores else None,
            "maximum": max(scores) if scores else None,
            "mean": float(np.mean(scores)) if scores else None,
            "standard_deviation": float(np.std(scores)) if scores else None,
        },
    }
