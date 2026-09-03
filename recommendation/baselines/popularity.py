from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import sparse


@dataclass
class PopularityBaseline:
    movie_ids: np.ndarray
    scores: np.ndarray
    counts: np.ndarray
    global_mean: float
    shrinkage: float

    @classmethod
    def fit(
        cls,
        ratings: sparse.csr_matrix,
        movie_ids: np.ndarray,
        *,
        shrinkage: float = 25.0,
    ) -> PopularityBaseline:
        counts = np.asarray((ratings != 0).sum(axis=0)).ravel().astype(np.int64)
        sums = np.asarray(ratings.sum(axis=0)).ravel()
        global_mean = float(ratings.data.mean()) if ratings.nnz else 0.0
        scores = (sums + shrinkage * global_mean) / (counts + shrinkage)
        return cls(movie_ids, scores, counts, global_mean, shrinkage)

    def predict(self, movie_id: int) -> float:
        index = int(np.searchsorted(self.movie_ids, movie_id))
        if index >= len(self.movie_ids) or self.movie_ids[index] != movie_id:
            return self.global_mean
        return float(self.scores[index])

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            directory / "popularity.npz",
            movie_ids=self.movie_ids,
            scores=self.scores,
            counts=self.counts,
        )
        (directory / "popularity.json").write_text(
            json.dumps(
                {
                    "global_mean": self.global_mean,
                    "shrinkage": self.shrinkage,
                    "movies": len(self.movie_ids),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
