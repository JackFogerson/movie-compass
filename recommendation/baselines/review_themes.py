from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

from recommendation.baselines.tmdb_content import metadata_text

REVIEW_STOP_WORDS = sorted(
    set(ENGLISH_STOP_WORDS).union(
        {
            "bad",
            "better",
            "best",
            "called",
            "does",
            "end",
            "ending",
            "feel",
            "felt",
            "film",
            "films",
            "good",
            "great",
            "got",
            "just",
            "like",
            "make",
            "makes",
            "man",
            "movie",
            "movies",
            "new",
            "older",
            "people",
            "recent",
            "really",
            "sense",
            "thing",
            "things",
            "time",
            "taken",
            "way",
        }
    )
)


@dataclass
class ReviewThemeModel:
    vectorizer: TfidfVectorizer
    profile: np.ndarray

    @classmethod
    def fit(
        cls,
        reviews_by_id: dict[int, str],
        ratings_by_id: dict[int, float],
        comparison_details: dict[int, dict],
    ) -> ReviewThemeModel:
        ids = sorted(
            tmdb_id
            for tmdb_id in set(reviews_by_id).intersection(ratings_by_id)
            if reviews_by_id[tmdb_id].strip()
        )
        if len(ids) < 10:
            raise ValueError("At least ten non-empty personal reviews are required")
        review_documents = [reviews_by_id[tmdb_id] for tmdb_id in ids]
        metadata_documents = [metadata_text(details) for details in comparison_details.values()]
        vectorizer = TfidfVectorizer(
            stop_words=REVIEW_STOP_WORDS,
            ngram_range=(1, 2),
            max_features=20_000,
            min_df=2,
            sublinear_tf=True,
        )
        vectorizer.fit(review_documents + metadata_documents)
        review_features = vectorizer.transform(review_documents)
        targets = np.array([ratings_by_id[tmdb_id] for tmdb_id in ids], dtype=np.float64)
        residuals = targets - targets.mean()
        profile = np.asarray(review_features.T @ residuals).ravel()
        norm = np.linalg.norm(profile)
        if norm:
            profile /= norm
        return cls(vectorizer, profile)

    def affinities(self, details_by_id: dict[int, dict]) -> dict[int, float]:
        ids = sorted(details_by_id)
        if not ids:
            return {}
        features = self.vectorizer.transform(
            [metadata_text(details_by_id[tmdb_id]) for tmdb_id in ids]
        )
        values = np.asarray(features @ self.profile).ravel()
        return {tmdb_id: float(values[index]) for index, tmdb_id in enumerate(ids)}

    def explanation_terms(self, details: dict, *, limit: int = 3) -> tuple[str, ...]:
        features: sparse.csr_matrix = self.vectorizer.transform([metadata_text(details)])
        contributions = features.multiply(self.profile).tocoo()
        ranked = sorted(
            (
                (float(value), int(column))
                for value, column in zip(contributions.data, contributions.col, strict=True)
                if value > 0
            ),
            reverse=True,
        )
        names = self.vectorizer.get_feature_names_out()
        return tuple(str(names[column]).replace("_", " ") for _, column in ranked[:limit])
