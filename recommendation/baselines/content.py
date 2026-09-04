from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge


def _feature_text(row: pd.Series) -> str:
    genre_value = row.get("genres")
    genres = "" if pd.isna(genre_value) else str(genre_value).replace("|", " ")
    year = row.get("year")
    decade = f"decade_{int(year) // 10 * 10}" if pd.notna(year) else "decade_unknown"
    return f"{genres} {decade}"


def _feature_texts(catalog: pd.DataFrame) -> pd.Series:
    """Vectorized equivalent of `_feature_text` for large candidate catalogs."""
    genres = catalog["genres"].fillna("").astype(str).str.replace("|", " ", regex=False)
    years = pd.to_numeric(catalog["year"], errors="coerce")
    decades = pd.Series("decade_unknown", index=catalog.index, dtype="object")
    known = years.notna()
    decades.loc[known] = (
        "decade_" + ((years.loc[known] // 10) * 10).astype(int).astype(str)
    )
    return genres + " " + decades


@dataclass
class ContentBaseline:
    vectorizer: TfidfVectorizer
    model: Ridge
    user_mean: float

    @classmethod
    def fit(cls, catalog: pd.DataFrame, personal_ratings: dict[int, float]) -> ContentBaseline:
        rated = catalog[catalog["movieId"].isin(personal_ratings)].copy()
        if len(rated) < 2:
            raise ValueError("At least two MovieLens-linked personal ratings are required")
        texts = _feature_texts(rated)
        vectorizer = TfidfVectorizer(token_pattern=r"(?u)\b[\w-]+\b")
        features = vectorizer.fit_transform(texts)
        targets = np.array(
            [personal_ratings[int(movie_id)] for movie_id in rated["movieId"]],
            dtype=np.float64,
        )
        user_mean = float(targets.mean())
        model = Ridge(alpha=5.0).fit(features, targets - user_mean)
        return cls(vectorizer, model, user_mean)

    def predict_catalog(self, catalog: pd.DataFrame) -> np.ndarray:
        features = self.vectorizer.transform(_feature_texts(catalog))
        return np.clip(self.user_mean + self.model.predict(features), 0.5, 5.0)

    def explanation_features(
        self, row: pd.Series, *, limit: int = 3
    ) -> tuple[str, ...]:
        features: sparse.csr_matrix = self.vectorizer.transform([_feature_text(row)])
        contributions = features.multiply(np.asarray(self.model.coef_).ravel()).tocoo()
        names = self.vectorizer.get_feature_names_out()
        ranked = sorted(
            (
                (float(value), str(names[int(column)]))
                for value, column in zip(contributions.data, contributions.col, strict=True)
                if value > 0
            ),
            reverse=True,
        )
        matches = []
        for _, name in ranked:
            if name.startswith("decade_"):
                decade = name.removeprefix("decade_")
                if decade == "unknown":
                    continue
                matches.append(f"release era: {decade}s")
            else:
                matches.append(f"genre: {name}")
            if len(matches) >= limit:
                break
        return tuple(matches)

    def caution_features(self, row: pd.Series, *, limit: int = 3) -> tuple[str, ...]:
        """Return candidate features associated with this user's lower ratings."""
        features: sparse.csr_matrix = self.vectorizer.transform([_feature_text(row)])
        contributions = features.multiply(np.asarray(self.model.coef_).ravel()).tocoo()
        names = self.vectorizer.get_feature_names_out()
        ranked = sorted(
            (
                (float(value), str(names[int(column)]))
                for value, column in zip(contributions.data, contributions.col, strict=True)
                if value < 0
            )
        )
        cautions = []
        for _, name in ranked:
            if name.startswith("decade_"):
                decade = name.removeprefix("decade_")
                if decade == "unknown":
                    continue
                cautions.append(f"release era: {decade}s")
            else:
                cautions.append(f"genre: {name}")
            if len(cautions) >= limit:
                break
        return tuple(cautions)
