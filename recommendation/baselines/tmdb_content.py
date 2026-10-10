from __future__ import annotations

import re
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
    "country": "production country",
    "company": "production company",
    "runtime": "runtime",
    "certification": "content rating",
}


def _token(prefix: str, value: str) -> str:
    # Keep structured names as one feature even when they contain initials or punctuation.
    # For example, "J.K. Simmons" must become cast_j_k_simmons rather than cast_j + k_simmons.
    normalized = "_".join(re.findall(r"[\w-]+", value.casefold()))
    return f"{prefix}_{normalized}"


def _meaningful_structured_value(prefix: str, value: str) -> bool:
    if prefix not in {"cast", "director"}:
        return True
    return any(len(part) > 1 for part in value.replace("-", " ").split())


def _runtime_bucket(details: dict) -> str | None:
    runtime = details.get("runtime")
    if not runtime:
        return None
    minutes = int(runtime)
    if minutes < 90:
        return "Under 90 minutes"
    if minutes < 120:
        return "90–119 minutes"
    if minutes < 150:
        return "120–149 minutes"
    return "150+ minutes"


def _content_rating(details: dict) -> str | None:
    if details.get("certification"):
        return str(details["certification"]).strip() or None
    release_rows = details.get("release_dates", {}).get("results", [])
    for country in release_rows:
        if country.get("iso_3166_1") != "US":
            continue
        release_priority = {3: 0, 2: 1, 4: 2, 5: 3, 6: 4, 1: 5}
        certifications = sorted(
            (
                item
                for item in country.get("release_dates", [])
                if str(item.get("certification") or "").strip()
            ),
            key=lambda item: release_priority.get(int(item.get("type") or 0), 9),
        )
        values = [
            str(item.get("certification") or "").strip()
            for item in certifications
        ]
        if values:
            return values[0]
    for country in details.get("content_ratings", {}).get("results", []):
        if country.get("iso_3166_1") == "US" and country.get("rating"):
            return str(country["rating"]).strip()
    return None


def _display_structured_value(details: dict, prefix: str, token_value: str) -> str:
    """Recover exact TMDB spelling after a person name was normalized for the model."""
    if prefix == "cast":
        rows = details.get("credits", {}).get("cast", [])[:8]
    elif prefix == "director":
        rows = [
            item
            for item in details.get("credits", {}).get("crew", [])
            if item.get("job") == "Director"
        ]
    elif prefix == "keyword":
        rows = details.get("keywords", {}).get("keywords", [])
    elif prefix == "genre":
        rows = details.get("genres", [])
    elif prefix == "country":
        rows = details.get("production_countries", [])
    elif prefix == "company":
        rows = details.get("production_companies", [])
    elif prefix == "runtime":
        value = _runtime_bucket(details)
        return value.casefold() if value else token_value.replace("_", " ")
    elif prefix == "certification":
        value = _content_rating(details)
        return value.casefold() if value else token_value.replace("_", " ")
    else:
        return token_value.replace("_", " ")
    expected = f"{prefix}_{token_value}"
    for item in rows:
        name = str(item.get("name") or "").strip()
        if name and _token(prefix, name) == expected:
            return name.casefold()
    return token_value.replace("_", " ")


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
    countries = [
        _token("country", item["name"])
        for item in details.get("production_countries", [])
        if item.get("name")
    ]
    companies = [
        _token("company", item["name"])
        for item in details.get("production_companies", [])
        if item.get("name")
    ]
    runtime_bucket = _runtime_bucket(details)
    runtime = [_token("runtime", runtime_bucket)] if runtime_bucket else []
    content_rating = _content_rating(details)
    certification = [_token("certification", content_rating)] if content_rating else []
    release = details.get("release_date") or ""
    decade = f"decade_{release[:3]}0" if release[:4].isdigit() else "decade_unknown"
    language = _token("language", details.get("original_language") or "unknown")
    weighted_tokens = (
        genres * 3
        + keywords * 2
        + directors * 3
        + cast
        + countries * 2
        + companies * 2
        + runtime
        + certification
    )
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
            readable = _display_structured_value(details, prefix, value)
            if not _meaningful_structured_value(prefix, readable):
                continue
            if prefix == "language" and readable in {"en", "unknown"}:
                # English is too common in this catalog to be a useful, readable warning.
                continue
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

    def caution_features(self, details: dict, *, limit: int = 5) -> tuple[str, ...]:
        """Return intelligible metadata associated with this user's lower ratings."""
        features = self.vectorizer.transform([metadata_text(details)])
        contributions = features.multiply(np.asarray(self.model.coef_).ravel()).tocoo()
        names = self.vectorizer.get_feature_names_out()
        ranked = sorted(
            (
                (float(value), str(names[int(column)]))
                for value, column in zip(contributions.data, contributions.col, strict=True)
                if value < 0
            )
        )
        explanations: list[str] = []
        seen: set[str] = set()
        for _, feature in ranked:
            if " " in feature or "_" not in feature:
                continue
            prefix, value = feature.split("_", 1)
            if prefix not in FEATURE_LABELS:
                continue
            readable = _display_structured_value(details, prefix, value)
            if not _meaningful_structured_value(prefix, readable):
                continue
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
