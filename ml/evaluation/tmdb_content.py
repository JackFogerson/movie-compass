from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from recommendation.baselines.tmdb_content import TmdbContentModel


@dataclass(frozen=True)
class TmdbContentEvaluation:
    seeds: tuple[int, ...]
    ratings: int
    mean_baseline_mae: float
    rich_content_mae: float
    mean_baseline_rmse: float
    rich_content_rmse: float


def evaluate_tmdb_content(
    details_by_id: dict[int, dict],
    ratings_by_id: dict[int, float],
    *,
    seeds: tuple[int, ...] = (1, 7, 21, 42, 84),
    test_fraction: float = 0.2,
    alpha: float = 8.0,
) -> TmdbContentEvaluation:
    ids = np.array(sorted(set(details_by_id).intersection(ratings_by_id)), dtype=np.int64)
    if len(ids) < 20:
        raise ValueError("At least twenty enriched ratings are required")
    baseline_absolute: list[float] = []
    rich_absolute: list[float] = []
    baseline_squared: list[float] = []
    rich_squared: list[float] = []
    for seed in seeds:
        shuffled = np.random.default_rng(seed).permutation(ids)
        test_size = max(2, int(round(len(ids) * test_fraction)))
        test_ids = shuffled[:test_size]
        train_ids = shuffled[test_size:]
        train_ratings = {int(value): ratings_by_id[int(value)] for value in train_ids}
        train_details = {int(value): details_by_id[int(value)] for value in train_ids}
        test_details = {int(value): details_by_id[int(value)] for value in test_ids}
        model = TmdbContentModel.fit(train_details, train_ratings, alpha=alpha)
        predictions = model.predict(test_details)
        for tmdb_id in test_ids:
            actual = ratings_by_id[int(tmdb_id)]
            baseline_error = actual - model.user_mean
            rich_error = actual - predictions[int(tmdb_id)]
            baseline_absolute.append(abs(baseline_error))
            rich_absolute.append(abs(rich_error))
            baseline_squared.append(baseline_error**2)
            rich_squared.append(rich_error**2)
    return TmdbContentEvaluation(
        seeds=seeds,
        ratings=len(ids),
        mean_baseline_mae=float(np.mean(baseline_absolute)),
        rich_content_mae=float(np.mean(rich_absolute)),
        mean_baseline_rmse=float(np.sqrt(np.mean(baseline_squared))),
        rich_content_rmse=float(np.sqrt(np.mean(rich_squared))),
    )
