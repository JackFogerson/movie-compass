from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from sklearn.decomposition import TruncatedSVD

from recommendation.baselines.popularity import PopularityBaseline


@dataclass(frozen=True)
class PersonalFactors:
    intercept: float
    factors: np.ndarray
    ratings_used: int


@dataclass
class LatentFactorModel:
    movie_ids: np.ndarray
    item_factors: np.ndarray
    item_baselines: np.ndarray
    global_mean: float
    factors: int
    random_state: int
    explained_variance: float

    @classmethod
    def fit(
        cls,
        ratings: sparse.csr_matrix,
        movie_ids: np.ndarray,
        *,
        factors: int = 64,
        random_state: int = 42,
    ) -> LatentFactorModel:
        if ratings.nnz == 0:
            raise ValueError("Collaborative training requires at least one rating")
        maximum = max(1, min(ratings.shape) - 1)
        effective_factors = min(factors, maximum)
        popularity = PopularityBaseline.fit(ratings, movie_ids)
        residual = ratings.astype(np.float32, copy=True)
        residual.data -= popularity.scores[residual.indices].astype(np.float32)
        svd = TruncatedSVD(n_components=effective_factors, random_state=random_state)
        svd.fit(residual)
        return cls(
            movie_ids=movie_ids.copy(),
            item_factors=svd.components_.T.astype(np.float32),
            item_baselines=popularity.scores.astype(np.float32),
            global_mean=popularity.global_mean,
            factors=effective_factors,
            random_state=random_state,
            explained_variance=float(svd.explained_variance_ratio_.sum()),
        )

    def _indices(self, movie_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        indices = np.searchsorted(self.movie_ids, movie_ids)
        covered = indices < len(self.movie_ids)
        safe = np.minimum(indices, len(self.movie_ids) - 1)
        covered &= self.movie_ids[safe] == movie_ids
        return safe, covered

    def fit_personal(
        self, personal_ratings: dict[int, float], *, regularization: float = 10.0
    ) -> PersonalFactors:
        ids = np.array(sorted(personal_ratings), dtype=np.int64)
        indices, covered = self._indices(ids)
        ids = ids[covered]
        indices = indices[covered]
        if len(ids) < 2:
            raise ValueError("At least two collaborative-covered personal ratings are required")
        targets = np.array([personal_ratings[int(movie_id)] for movie_id in ids])
        targets -= self.item_baselines[indices]
        design = np.column_stack([np.ones(len(indices)), self.item_factors[indices]])
        penalty = np.eye(design.shape[1]) * regularization
        penalty[0, 0] = 1.0
        coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ targets)
        return PersonalFactors(float(coefficients[0]), coefficients[1:], len(ids))

    def predict(self, personal: PersonalFactors, movie_ids: np.ndarray) -> np.ndarray:
        ids = np.asarray(movie_ids, dtype=np.int64)
        indices, covered = self._indices(ids)
        predictions = np.full(len(ids), self.global_mean + personal.intercept, dtype=np.float64)
        predictions[covered] = (
            self.item_baselines[indices[covered]]
            + personal.intercept
            + self.item_factors[indices[covered]] @ personal.factors
        )
        return np.clip(predictions, 0.5, 5.0)
