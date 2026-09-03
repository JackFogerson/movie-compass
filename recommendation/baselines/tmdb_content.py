from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge

FEATURE_LABELS = {
    "genre": "genre",
    "keyword": "story/theme",
    "director": "director",
    "cast": "cast member",
    "decade": "release era",
    "language": "original language",
}


def _token(prefix: str, value: str) -> str:
    return f"{prefix}_{'_'.join(value.casefold().split())}"


def metadata_text(details: dict) -> str:
    genres = [_token("genre", item["name"]) for item in details.get("genres", [])]
    keyword_rows = details.get("keywords", {}).get("keywords", [])
    keywords = [_token("keyword", item["name"]) for item in keyword_rows]
    crew = details.get("credits", {}).get("crew", [])
    directors = [_token("director", item["name"]) for item in crew if item.get("job") == "Director"]
    cast = [
        _token("cast", item["name"])
        for item in details.get("credits", {}).get("cast", [])[:8]
        if item.get("name")
    ]
    release = details.get("release_date") or ""
    decade = f"decade_{release[:3]}0" if release[:4].isdigit() else "decade_unknown"
    language = _token("language", details.get("original_language") or "unknown")
    weighted_tokens = genres * 3 + keywords * 2 + directors * 3 + cast
    return " ".join(
        [*weighted_tokens, decade, language, details.get("overview") or ""]
    )


@dataclass
class TmdbContentModel:
    vectorizer: TfidfVectorizer
    model: Ridge
    user_mean: float

    @classmethod
    def fit(
        cls,
        details_by_id: dict[int, dict],
        ratings_by_id: dict[int, float],
        *,
        alpha: float = 0.5,
    ):
        ids = sorted(set(details_by_id).intersection(ratings_by_id))
        if len(ids) < 10:
            raise ValueError("At least ten enriched personal movies are required")
        texts = [metadata_text(details_by_id[tmdb_id]) for tmdb_id in ids]
        targets = np.array([ratings_by_id[tmdb_id] for tmdb_id in ids], dtype=np.float64)
        vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=15_000,
            min_df=1,
            token_pattern=r"(?u)\b[\w-]+\b",
        )
        features = vectorizer.fit_transform(texts)
        user_mean = float(targets.mean())
        model = Ridge(alpha=alpha).fit(features, targets - user_mean)
        return cls(vectorizer, model, user_mean)

    def predict(self, details_by_id: dict[int, dict]) -> dict[int, float]:
        ids = sorted(details_by_id)
        features = self.vectorizer.transform([metadata_text(details_by_id[value]) for value in ids])
        predictions = np.clip(self.user_mean + self.model.predict(features), 0.5, 5.0)
        return {tmdb_id: float(predictions[index]) for index, tmdb_id in enumerate(ids)}

    def explanation_features(self, details: dict, *, limit: int = 5) -> tuple[str, ...]:
        """Return the candidate metadata that contributes most positively for this user."""
        features = self.vectorizer.transform([metadata_text(details)])
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
        explanations: list[str] = []
        seen: set[str] = set()
        for _, feature in ranked:
            # Structured metadata tokens are much more intelligible than arbitrary
            # synopsis n-grams, and avoid presenting coincidental words as evidence.
            if " " in feature or "_" not in feature:
                continue
            prefix, value = feature.split("_", 1)
            if prefix not in FEATURE_LABELS:
                continue
            readable = value.replace("_", " ")
            if prefix == "decade" and readable.isdigit():
                readable = f"{readable}s"
            label = f"{FEATURE_LABELS[prefix]}: {readable}"
            if label in seen:
                continue
            seen.add(label)
            explanations.append(label)
            if len(explanations) >= limit:
                break
        return tuple(explanations)
