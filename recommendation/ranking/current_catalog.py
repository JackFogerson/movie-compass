from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

import numpy as np
import pandas as pd

from recommendation.baselines.content import ContentBaseline
from recommendation.baselines.popularity import PopularityBaseline
from recommendation.calibration.rating_interval import RatingInterval
from recommendation.collaborative.latent_factor import LatentFactorModel, PersonalFactors
from recommendation.ranking.hybrid import HybridWeights, hybrid_predictions

TMDB_GENRES = {
    28: "Action",
    12: "Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Children",
    14: "Fantasy",
    36: "History",
    27: "Horror",
    10402: "Musical",
    9648: "Mystery",
    10749: "Romance",
    878: "Sci-Fi",
    53: "Thriller",
    10752: "War",
    37: "Western",
}

POPULARITY_TIERS = {
    "all",
    "blockbuster",
    "popular",
    "cult_classic",
    "under_the_radar",
    "unknown",
}


def _join_naturally(values: list[str]) -> str:
    if len(values) <= 1:
        return values[0] if values else "movies with a similar overall profile"
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def meaningful_metadata_match(match: str) -> bool:
    """Reject malformed person features such as a lone initial from older artifacts."""
    kind, separator, value = str(match).partition(":")
    if not separator or not value.strip():
        return False
    if kind.strip() not in {"director", "cast member"}:
        return True
    return any(len(part) > 1 for part in value.replace("-", " ").split())


def humanize_metadata_matches(matches: tuple[str, ...]) -> str:
    readable: list[str] = []
    for match in matches:
        if not meaningful_metadata_match(match):
            continue
        kind, _, value = match.partition(": ")
        if kind == "genre":
            readable.append(f"{value} films")
        elif kind == "story/theme":
            readable.append(f"stories involving {value}")
        elif kind == "director":
            readable.append(f"films directed by {value.title()}")
        elif kind == "cast member":
            readable.append(f"films featuring {value.title()}")
        elif kind == "release era":
            readable.append(f"films from the {value}")
        elif kind == "original language":
            readable.append(f"{value.upper()}-language films")
        else:
            readable.append(value or match)
    return _join_naturally(readable)


def describe_positive_matches(matches: tuple[str, ...]) -> str:
    """Describe positive taste evidence as a natural sentence instead of model labels."""
    matches = tuple(match for match in matches if meaningful_metadata_match(match))
    if not matches:
        return "Its overall style resembles movies that have worked well for you."
    return f"{humanize_metadata_matches(matches).capitalize()} have been reliable matches for you."


def humanize_caution_matches(matches: tuple[str, ...]) -> str:
    """Turn negative model features into direct, natural-language cautions."""
    readable: list[str] = []
    for match in matches:
        if not meaningful_metadata_match(match):
            continue
        kind, _, value = match.partition(": ")
        value = value.strip()
        if kind == "genre":
            readable.append(f"you have tended to rate {value.casefold()} films lower")
        elif kind == "story/theme":
            if len(value) == 5 and value[:4].isdigit() and value.endswith("s"):
                readable.append(
                    f"period stories set in the {value} have been less reliable for you"
                )
            else:
                readable.append(
                    f"stories centered on {value} have been less consistent matches for you"
                )
        elif kind == "director":
            readable.append(f"films directed by {value.title()} have been a mixed fit for you")
        elif kind == "cast member":
            readable.append(
                f"films featuring {value.title()} have not matched your taste as consistently"
            )
        elif kind == "release era":
            readable.append(f"movies from the {value} have usually scored lower for you")
        elif kind == "original language":
            language_names = {
                "de": "German",
                "es": "Spanish",
                "fr": "French",
                "it": "Italian",
                "ja": "Japanese",
                "ko": "Korean",
                "zh": "Chinese",
            }
            language = language_names.get(value.casefold(), value.upper())
            readable.append(
                f"{language}-language films have been less predictable matches for you"
            )
    return _join_naturally(readable)


def classify_popularity(year: int | None, evidence_count: int) -> str:
    """Classify audience reach; this is deliberately separate from predicted quality."""
    if evidence_count >= 10_000:
        return "blockbuster"
    if evidence_count >= 2_500:
        return "popular"
    if evidence_count >= 250 and year is not None and year <= date.today().year - 10:
        return "cult_classic"
    if evidence_count >= 25:
        return "under_the_radar"
    return "unknown"


@dataclass(frozen=True)
class RankedMovie:
    rank: int
    tmdb_id: int
    movielens_id: int | None
    title: str
    release_date: str | None
    year: int | None
    genres: tuple[str, ...]
    runtime: int | None
    score: float
    score_mode: str
    candidate_origin: str
    content_score: float
    content_model: str
    collaborative_score: float | None
    popularity_score: float | None
    popularity_tier: str
    audience_evidence_count: int
    tmdb_vote_average: float
    tmdb_vote_count: int
    review_theme_affinity: float | None
    media_type: str = "movie"
    relative_to_profile: str = "typical"
    plausible_rating_min: float | None = None
    plausible_rating_max: float | None = None
    interval_coverage: float | None = None
    interval_samples: int = 0
    interval_method: str | None = None
    metadata_matches: tuple[str, ...] = ()
    caution_matches: tuple[str, ...] = ()
    explanation: tuple[str, ...] = ()
    model_weights: dict[str, float] | None = None
    public_rating_prior: float | None = None

    def to_dict(self) -> dict:
        result = asdict(self)
        if self.score_mode == "hybrid":
            evidence_level = "collaborative_supported"
            support = (
                f"MovieLens viewers with similar taste predict {self.collaborative_score:.2f}/5"
            )
        else:
            evidence_level = "cold_start"
            support = (
                f"This title has no MovieLens history, so its {self.score:.2f}/5 estimate "
                f"uses personal metadata fit and {self.tmdb_vote_count:,} TMDB votes"
            )
        if self.relative_to_profile == "below_typical":
            personal = (
                "This falls below your usual rating because its learned taste signals are weak. "
            )
            if self.metadata_matches:
                personal = (
                    f"{describe_positive_matches(self.metadata_matches)} Even so, "
                    "the overall evidence suggests this may be a tougher match. "
                )
        else:
            personal = (
                f"{describe_positive_matches(self.metadata_matches)} "
                if self.metadata_matches
                else "Its overall profile resembles movies you rated highly. "
            )
        if self.score_mode == "hybrid":
            support = f"Viewers with similar tastes predict {self.collaborative_score:.2f}/5"
        result["expected_rating"] = self.score
        result["rating_uncertainty"] = {
            "plausible_minimum": self.plausible_rating_min,
            "plausible_maximum": self.plausible_rating_max,
            "coverage": self.interval_coverage,
            "heldout_samples": self.interval_samples,
            "method": self.interval_method,
        }
        positive_summary = describe_positive_matches(self.metadata_matches)
        result["why_you_may_like_it"] = [positive_summary]
        result["why_you_may_like_it"].extend(
            reason
            for reason in self.explanation[1:]
            if not reason.startswith("Specific positive matches") and reason != positive_summary
        )
        cautions: list[str] = []
        if self.caution_matches:
            cautions.append(
                f"One possible concern: {humanize_caution_matches(self.caution_matches)}."
            )
        if self.relative_to_profile == "below_typical":
            cautions.append(
                "Taken together, the learned signals place this below your usual rating, "
                "even if a few elements still match your taste."
            )
        elif not cautions:
            cautions.append(
                "No strong personal warning stands out; the main uncertainty is whether the "
                "movie's execution will live up to the traits that match your taste."
            )
        result["why_you_may_not_like_it"] = cautions
        result["ranking_expectation"] = {
            "expected_rating": self.score,
            "evidence_level": evidence_level,
            "reason": f"{personal}{support}.",
            "calculation": (
                " + ".join(
                    [
                        f"{round(100 * value)}% {label}"
                        for label, value in (self.model_weights or {}).items()
                    ]
                )
                if self.model_weights
                else "55% collaborative fit + 35% personal metadata fit + 10% popularity prior"
                if self.score_mode == "hybrid"
                else "80% personal metadata fit + 20% reliability-adjusted TMDB rating"
            ),
        }
        return result


def _candidate_frame(candidates: list[dict], movielens_by_tmdb: dict[int, int]) -> pd.DataFrame:
    rows = []
    for candidate in candidates:
        release_date = candidate.get("release_date") or ""
        year = int(release_date[:4]) if release_date[:4].isdigit() else np.nan
        tmdb_id = int(candidate["id"])
        if candidate.get("genre_ids") is not None:
            genres = tuple(
                TMDB_GENRES[genre_id]
                for genre_id in candidate.get("genre_ids", [])
                if genre_id in TMDB_GENRES
            )
        else:
            genres = tuple(item["name"] for item in candidate.get("genres", []))
        rows.append(
            {
                "tmdb_id": tmdb_id,
                "movieId": movielens_by_tmdb.get(
                    tmdb_id,
                    tmdb_id if tmdb_id < 0 else -tmdb_id,
                ),
                "title": candidate.get("title") or candidate.get("original_title") or "Untitled",
                "release_date": release_date or None,
                "year": year,
                "genres": "|".join(genres),
                "genre_names": genres,
                "runtime": candidate.get("runtime"),
                "media_type": candidate.get("media_type") or (
                    "tv" if int(candidate["id"]) < 0 else "movie"
                ),
                "vote_average": float(candidate.get("vote_average") or 0.0),
                "vote_count": int(candidate.get("vote_count") or 0),
            }
        )
    return pd.DataFrame(rows)


def rank_current_candidates(
    candidates: list[dict],
    *,
    excluded_tmdb_ids: set[int],
    movielens_by_tmdb: dict[int, int],
    content: ContentBaseline,
    collaborative: LatentFactorModel,
    personal_factors: PersonalFactors,
    popularity: PopularityBaseline,
    user_mean: float,
    rich_content_scores: dict[int, float] | None = None,
    candidate_origins: dict[int, str] | None = None,
    review_affinities: dict[int, float] | None = None,
    review_terms: dict[int, tuple[str, ...]] | None = None,
    metadata_matches: dict[int, tuple[str, ...]] | None = None,
    metadata_cautions: dict[int, tuple[str, ...]] | None = None,
    movielens_rating_counts: dict[int, int] | None = None,
    popularity_tier: str = "all",
    limit: int = 20,
    max_per_primary_genre: int = 4,
    descending: bool = True,
    rating_interval: RatingInterval | None = None,
    review_signal_scale: float = 0.0,
    hybrid_weights: HybridWeights | None = None,
    cold_start_weights: dict[str, float] | None = None,
) -> list[RankedMovie]:
    if popularity_tier not in POPULARITY_TIERS:
        raise ValueError(f"Invalid popularity tier: {popularity_tier}")
    deduplicated = {
        int(item["id"]): item
        for item in candidates
        if item.get("id") is not None and int(item["id"]) not in excluded_tmdb_ids
    }
    if not deduplicated:
        return []
    frame = _candidate_frame(list(deduplicated.values()), movielens_by_tmdb)
    content_scores = content.predict_catalog(frame)
    if rich_content_scores:
        content_scores = np.array(
            [
                rich_content_scores.get(int(tmdb_id), float(content_scores[index]))
                for index, tmdb_id in enumerate(frame["tmdb_id"])
            ]
        )
    if review_signal_scale and review_affinities:
        affinities = np.array(
            [float(review_affinities.get(int(tmdb_id), 0.0)) for tmdb_id in frame["tmdb_id"]]
        )
        content_scores = np.clip(content_scores + review_signal_scale * affinities, 0.5, 5.0)
    movie_ids = frame["movieId"].to_numpy(dtype=np.int64)
    linked = movie_ids > 0
    collaborative_scores = collaborative.predict(personal_factors, movie_ids)
    popularity_scores = np.array([popularity.predict(int(value)) for value in movie_ids])
    effective_hybrid_weights = hybrid_weights or HybridWeights()
    normalized_hybrid_weights = effective_hybrid_weights.normalized()
    hybrid_scores = hybrid_predictions(
        collaborative_scores,
        content_scores,
        popularity_scores,
        effective_hybrid_weights,
    )
    vote_reliability = frame["vote_count"].to_numpy(dtype=float)
    vote_reliability = vote_reliability / (vote_reliability + 250.0)
    public_quality = frame["vote_average"].to_numpy(dtype=float) / 2.0
    quality_prior = vote_reliability * public_quality + (1.0 - vote_reliability) * user_mean
    cold_metadata_weight = float((cold_start_weights or {}).get("metadata", 0.8))
    cold_public_weight = float((cold_start_weights or {}).get("public_rating", 0.2))
    cold_weight_total = cold_metadata_weight + cold_public_weight
    if cold_metadata_weight < 0 or cold_public_weight < 0 or cold_weight_total <= 0:
        raise ValueError("Cold-start weights must be non-negative with a positive sum")
    cold_metadata_weight /= cold_weight_total
    cold_public_weight /= cold_weight_total
    cold_start_scores = (
        cold_metadata_weight * content_scores + cold_public_weight * quality_prior
    )
    final_scores = np.where(linked, hybrid_scores, cold_start_scores)

    order = np.argsort(-final_scores if descending else final_scores)
    selected: list[RankedMovie] = []
    primary_genre_counts: dict[str, int] = {}
    for position in order:
        row = frame.iloc[int(position)]
        genres = tuple(row["genre_names"])
        primary_genre = genres[0] if genres else "Unknown"
        if primary_genre_counts.get(primary_genre, 0) >= max_per_primary_genre:
            continue
        primary_genre_counts[primary_genre] = primary_genre_counts.get(primary_genre, 0) + 1
        is_linked = bool(linked[position])
        tmdb_id = int(row["tmdb_id"])
        movie_id = int(row["movieId"])
        evidence_count = max(
            int(row["vote_count"]),
            int((movielens_rating_counts or {}).get(movie_id, 0)) if is_linked else 0,
        )
        tier = classify_popularity(
            int(row["year"]) if pd.notna(row["year"]) else None,
            evidence_count,
        )
        if popularity_tier != "all" and tier != popularity_tier:
            continue
        matched_terms = (review_terms or {}).get(tmdb_id, ())
        personal_matches = (metadata_matches or {}).get(tmdb_id, ())
        if not personal_matches:
            personal_matches = content.explanation_features(row)
        personal_matches = tuple(
            match for match in personal_matches if meaningful_metadata_match(match)
        )
        caution_matches = (metadata_cautions or {}).get(tmdb_id, ())
        if not caution_matches:
            caution_matches = content.caution_features(row)
        caution_matches = tuple(
            match for match in caution_matches if meaningful_metadata_match(match)
        )
        reasons = [
            (
                "Supported by MovieLens collaborative and personal content signals."
                if is_linked
                else "Matched from current TMDB metadata without claiming collaborative history."
            )
        ]
        affinity = (review_affinities or {}).get(tmdb_id)
        interval = rating_interval.apply(float(final_scores[position])) if rating_interval else None
        if matched_terms and affinity is not None and affinity >= 0.003:
            reasons.append(
                "Your higher-rated reviews emphasize "
                f"{', '.join(matched_terms)}; this movie's synopsis and metadata overlap "
                "with those themes."
            )
            if review_signal_scale:
                reasons.append("For this profile, review themes also improved held-out accuracy.")
        if personal_matches:
            reasons.append(
                describe_positive_matches(tuple(personal_matches))
            )
        selected.append(
            RankedMovie(
                rank=len(selected) + 1,
                tmdb_id=tmdb_id,
                movielens_id=int(row["movieId"]) if is_linked else None,
                title=str(row["title"]),
                release_date=row["release_date"],
                year=int(row["year"]) if pd.notna(row["year"]) else None,
                genres=genres,
                runtime=(
                    int(row["runtime"])
                    if pd.notna(row.get("runtime")) and int(row["runtime"]) > 0
                    else None
                ),
                score=round(float(final_scores[position]), 4),
                score_mode="hybrid" if is_linked else "cold_start",
                candidate_origin=(candidate_origins or {}).get(int(row["tmdb_id"]), "tmdb_recent"),
                content_score=round(float(content_scores[position]), 4),
                content_model=(
                    "tmdb_metadata"
                    if rich_content_scores and int(row["tmdb_id"]) in rich_content_scores
                    else "genre_decade"
                ),
                collaborative_score=(
                    round(float(collaborative_scores[position]), 4) if is_linked else None
                ),
                popularity_score=(
                    round(float(popularity_scores[position]), 4) if is_linked else None
                ),
                popularity_tier=tier,
                audience_evidence_count=evidence_count,
                tmdb_vote_average=float(row["vote_average"]),
                tmdb_vote_count=int(row["vote_count"]),
                review_theme_affinity=(
                    round(float(review_affinities[tmdb_id]), 4)
                    if review_affinities and tmdb_id in review_affinities
                    else None
                ),
                media_type=str(row.get("media_type") or "movie"),
                relative_to_profile=(
                    "below_typical"
                    if float(final_scores[position]) < user_mean - 0.25
                    else "above_typical"
                    if float(final_scores[position]) > user_mean + 0.25
                    else "typical"
                ),
                plausible_rating_min=interval[0] if interval else None,
                plausible_rating_max=interval[1] if interval else None,
                interval_coverage=rating_interval.coverage if rating_interval else None,
                interval_samples=rating_interval.samples if rating_interval else 0,
                interval_method=rating_interval.method if rating_interval else None,
                metadata_matches=personal_matches,
                caution_matches=caution_matches,
                explanation=tuple(reasons),
                model_weights=(
                    {
                        "collaborative fit": float(normalized_hybrid_weights[0]),
                        "personal metadata fit": float(normalized_hybrid_weights[1]),
                        "popularity prior": float(normalized_hybrid_weights[2]),
                    }
                    if is_linked
                    else {
                        "personal metadata fit": cold_metadata_weight,
                        "reliability-adjusted public rating": cold_public_weight,
                    }
                ),
                public_rating_prior=(
                    None if is_linked else round(float(quality_prior[position]), 4)
                ),
            )
        )
        if len(selected) >= limit:
            break
    return selected


def preselect_movielens_candidates(
    catalog: pd.DataFrame,
    *,
    excluded_tmdb_ids: set[int],
    content: ContentBaseline,
    collaborative: LatentFactorModel,
    personal_factors: PersonalFactors,
    popularity: PopularityBaseline,
    limit: int = 250,
    minimum_ratings: int = 100,
    year_min: int | None = None,
    year_max: int | None = None,
    hybrid_weights: HybridWeights | None = None,
) -> list[int]:
    eligible = catalog[catalog["tmdb_id"].notna()].copy()
    eligible["tmdb_id"] = eligible["tmdb_id"].astype(int)
    eligible = eligible[~eligible["tmdb_id"].isin(excluded_tmdb_ids)]
    if year_min is not None:
        eligible = eligible[eligible["year"] >= year_min]
    if year_max is not None:
        eligible = eligible[eligible["year"] <= year_max]
    if eligible.empty:
        return []
    ids = eligible["movieId"].to_numpy(dtype=np.int64)
    positions = np.searchsorted(popularity.movie_ids, ids)
    counts = popularity.counts[positions]
    eligible = eligible[counts >= minimum_ratings].copy()
    if eligible.empty:
        return []
    ids = eligible["movieId"].to_numpy(dtype=np.int64)
    content_scores = content.predict_catalog(eligible)
    collaborative_scores = collaborative.predict(personal_factors, ids)
    popularity_scores = np.array([popularity.predict(int(value)) for value in ids])
    scores = hybrid_predictions(
        collaborative_scores,
        content_scores,
        popularity_scores,
        hybrid_weights,
    )
    order = np.argsort(-scores)[:limit]
    return [int(eligible.iloc[int(position)]["tmdb_id"]) for position in order]
