from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from recommendation.baselines.review_themes import ReviewThemeModel
from recommendation.baselines.tmdb_content import TmdbContentModel


@dataclass(frozen=True)
class ReviewThemeEvaluation:
    seeds: tuple[int, ...]
    ratings: int
    scale: float
    rich_content_mae: float
    combined_mae: float
    rich_content_rmse: float
    combined_rmse: float


def evaluate_review_themes(
    details_by_id: dict[int, dict],
    ratings_by_id: dict[int, float],
    reviews_by_id: dict[int, str],
    *,
    scale: float = 0.5,
    seeds: tuple[int, ...] = (1, 7, 21, 42, 84),
    test_fraction: float = 0.2,
) -> ReviewThemeEvaluation:
    ids = np.array(
        sorted(set(details_by_id).intersection(ratings_by_id, reviews_by_id)), dtype=np.int64
    )
    if len(ids) < 15:
        raise ValueError("At least fifteen enriched ratings with reviews are required")
    rich_errors: list[float] = []
    combined_errors: list[float] = []
    for seed in seeds:
        shuffled = np.random.default_rng(seed).permutation(ids)
        test_size = max(2, int(round(len(ids) * test_fraction)))
        test_ids = shuffled[:test_size]
        train_ids = shuffled[test_size:]
        train_ratings = {int(value): ratings_by_id[int(value)] for value in train_ids}
        train_details = {int(value): details_by_id[int(value)] for value in train_ids}
        train_reviews = {int(value): reviews_by_id[int(value)] for value in train_ids}
        test_details = {int(value): details_by_id[int(value)] for value in test_ids}
        rich = TmdbContentModel.fit(train_details, train_ratings)
        rich_predictions = rich.predict(test_details)
        themes = ReviewThemeModel.fit(train_reviews, train_ratings, details_by_id)
        affinities = themes.affinities(test_details)
        for tmdb_id in test_ids:
            actual = ratings_by_id[int(tmdb_id)]
            rich_prediction = rich_predictions[int(tmdb_id)]
            combined_prediction = np.clip(
                rich_prediction + scale * affinities[int(tmdb_id)], 0.5, 5.0
            )
            rich_errors.append(actual - rich_prediction)
            combined_errors.append(actual - combined_prediction)
    rich_values = np.array(rich_errors)
    combined_values = np.array(combined_errors)
    return ReviewThemeEvaluation(
        seeds=seeds,
        ratings=len(ids),
        scale=scale,
        rich_content_mae=float(np.mean(np.abs(rich_values))),
        combined_mae=float(np.mean(np.abs(combined_values))),
        rich_content_rmse=float(np.sqrt(np.mean(rich_values**2))),
        combined_rmse=float(np.sqrt(np.mean(combined_values**2))),
    )
