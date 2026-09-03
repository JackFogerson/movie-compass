from pathlib import Path

import numpy as np
import pandas as pd
from app.services.model_weights import select_personalized_weights
from scipy import sparse

from ml.evaluation.personal import evaluate_personal_ratings
from recommendation.baselines.popularity import PopularityBaseline
from recommendation.collaborative.latent_factor import LatentFactorModel
from recommendation.ranking.hybrid import HybridWeights, hybrid_predictions


def _ratings() -> tuple[sparse.csr_matrix, np.ndarray]:
    matrix = sparse.csr_matrix(
        [
            [5, 4, 1, 2, 5, 0, 1, 0, 4, 2, 5, 1],
            [4, 5, 1, 2, 4, 1, 0, 2, 5, 1, 4, 2],
            [1, 2, 5, 4, 1, 5, 4, 5, 1, 4, 2, 5],
            [2, 1, 4, 5, 2, 4, 5, 4, 2, 5, 1, 4],
        ],
        dtype=np.float32,
    )
    return matrix, np.arange(1, 13, dtype=np.int64)


def test_personal_factors_and_hybrid_predict_on_rating_scale() -> None:
    ratings, movie_ids = _ratings()
    model = LatentFactorModel.fit(ratings, movie_ids, factors=2)
    personal = model.fit_personal({1: 5.0, 2: 4.5, 3: 1.0, 4: 2.0})
    predictions = model.predict(personal, np.array([5, 6, 99]))
    assert predictions.shape == (3,)
    assert np.all((predictions >= 0.5) & (predictions <= 5.0))
    combined = hybrid_predictions(
        predictions,
        np.array([4.0, 3.0, 2.0]),
        np.array([3.5, 3.5, 3.5]),
        HybridWeights(),
    )
    assert combined.shape == predictions.shape


def test_heldout_evaluator_compares_all_four_models_reproducibly() -> None:
    ratings, movie_ids = _ratings()
    catalog = pd.DataFrame(
        {
            "movieId": movie_ids,
            "genres": ["Drama", "Drama", "Comedy", "Comedy"] * 3,
            "year": np.arange(2000, 2012),
        }
    )
    personal_ratings = {
        int(movie_id): float(rating)
        for movie_id, rating in zip(
            movie_ids, [5, 4.5, 1, 2, 5, 4, 1, 2, 4.5, 2, 5, 1], strict=True
        )
    }
    popularity = PopularityBaseline.fit(ratings, movie_ids)
    collaborative = LatentFactorModel.fit(ratings, movie_ids, factors=2, random_state=7)
    first = evaluate_personal_ratings(catalog, personal_ratings, popularity, collaborative, seed=9)
    second = evaluate_personal_ratings(catalog, personal_ratings, popularity, collaborative, seed=9)
    assert set(first.metrics) == {"popularity", "content", "collaborative", "hybrid"}
    assert first.to_dict() == second.to_dict()
    assert all(metric.predictions == first.test_ratings for metric in first.metrics.values())


def test_personalized_weights_support_a_small_profile(tmp_path: Path) -> None:
    ratings, movie_ids = _ratings()
    catalog = pd.DataFrame(
        {
            "movieId": movie_ids,
            "genres": ["Drama", "Drama", "Comedy", "Comedy"] * 3,
            "year": np.arange(2000, 2012),
        }
    )
    personal = {
        int(movie_id): float(value)
        for movie_id, value in zip(movie_ids[:9], [5, 4.5, 1, 2, 5, 4, 1, 2, 4.5], strict=True)
    }
    popularity = PopularityBaseline.fit(ratings, movie_ids)
    collaborative = LatentFactorModel.fit(ratings, movie_ids, factors=2, random_state=7)
    policy = select_personalized_weights(
        tmp_path / "weights.json",
        catalog,
        personal,
        popularity,
        collaborative,
    )

    assert policy["ratings_used"] == 9
    assert policy["heldout_predictions"] == 10
    assert abs(sum(policy["weights"].values()) - 1.0) < 0.001
    assert abs(sum(policy["cold_start_weights"].values()) - 1.0) < 0.001
