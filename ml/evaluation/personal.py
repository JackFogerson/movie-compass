from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from recommendation.baselines.content import ContentBaseline
from recommendation.baselines.popularity import PopularityBaseline
from recommendation.collaborative.latent_factor import LatentFactorModel
from recommendation.ranking.hybrid import HybridWeights, hybrid_predictions


@dataclass(frozen=True)
class RegressionMetrics:
    mae: float
    rmse: float
    predictions: int


@dataclass(frozen=True)
class PersonalEvaluation:
    seed: int
    test_fraction: float
    train_ratings: int
    test_ratings: int
    metrics: dict[str, RegressionMetrics]
    errors: list[dict[str, float | int]]

    def to_dict(self) -> dict:
        result = asdict(self)
        result["metrics"] = {name: asdict(value) for name, value in self.metrics.items()}
        return result


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> RegressionMetrics:
    errors = actual - predicted
    return RegressionMetrics(
        mae=float(np.mean(np.abs(errors))),
        rmse=float(np.sqrt(np.mean(errors**2))),
        predictions=len(actual),
    )


def evaluate_personal_ratings(
    catalog: pd.DataFrame,
    personal_ratings: dict[int, float],
    popularity: PopularityBaseline,
    collaborative: LatentFactorModel,
    *,
    test_fraction: float = 0.2,
    seed: int = 42,
    hybrid_weights: HybridWeights | None = None,
    minimum_ratings: int = 10,
) -> PersonalEvaluation:
    linked_ids = np.array(
        sorted(set(personal_ratings).intersection(int(value) for value in catalog["movieId"])),
        dtype=np.int64,
    )
    if len(linked_ids) < minimum_ratings:
        raise ValueError(
            f"At least {minimum_ratings} MovieLens-linked personal ratings are required"
        )
    rng = np.random.default_rng(seed)
    shuffled = rng.permutation(linked_ids)
    test_size = max(2, int(round(len(shuffled) * test_fraction)))
    test_ids = shuffled[:test_size]
    train_ids = shuffled[test_size:]
    train = {int(movie_id): personal_ratings[int(movie_id)] for movie_id in train_ids}
    actual = np.array([personal_ratings[int(movie_id)] for movie_id in test_ids])

    content_model = ContentBaseline.fit(catalog, train)
    personal_factors = collaborative.fit_personal(train)
    catalog_predictions = content_model.predict_catalog(catalog)
    catalog_positions = pd.Series(np.arange(len(catalog)), index=catalog["movieId"].astype(int))
    content_predictions = np.array(
        [catalog_predictions[int(catalog_positions.loc[int(movie_id)])] for movie_id in test_ids]
    )
    collaborative_predictions = collaborative.predict(personal_factors, test_ids)
    popularity_predictions = np.array([popularity.predict(int(movie_id)) for movie_id in test_ids])
    hybrid = hybrid_predictions(
        collaborative_predictions,
        content_predictions,
        popularity_predictions,
        hybrid_weights or HybridWeights(),
    )
    predictions = {
        "popularity": popularity_predictions,
        "content": content_predictions,
        "collaborative": collaborative_predictions,
        "hybrid": hybrid,
    }
    errors = [
        {
            "movie_id": int(movie_id),
            "actual": float(actual[index]),
            **{name: float(values[index]) for name, values in predictions.items()},
        }
        for index, movie_id in enumerate(test_ids)
    ]
    return PersonalEvaluation(
        seed=seed,
        test_fraction=test_fraction,
        train_ratings=len(train_ids),
        test_ratings=len(test_ids),
        metrics={name: _metrics(actual, values) for name, values in predictions.items()},
        errors=errors,
    )
