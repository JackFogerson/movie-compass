from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd
import typer
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.db.models import Movie, User, UserMovieInteraction
from app.db.session import SessionLocal
from app.services.model_weights import select_personalized_weights, weights_from_policy
from app.services.personal_ratings import (
    linked_personal_ratings,
    personal_tmdb_ratings,
    personal_tmdb_reviews,
)
from app.services.profile_stats import (
    METADATA_FILTER_CATEGORIES,
    matches_metadata_filter,
)
from app.services.review_policy import load_review_policy
from ingestion.tmdb.client import TmdbClient, normalize_tv_search_result
from ingestion.tmdb.details_cache import load_or_fetch_details
from ml.artifacts.movielens import load_movielens_artifacts
from ml.evaluation.ranking import compute_ranking_metrics
from recommendation.baselines.content import ContentBaseline
from recommendation.baselines.popularity import PopularityBaseline
from recommendation.baselines.review_themes import ReviewThemeModel
from recommendation.baselines.tmdb_content import TmdbContentModel
from recommendation.calibration.rating_interval import RatingInterval
from recommendation.collaborative.latent_factor import LatentFactorModel
from recommendation.ranking.current_catalog import (
    POPULARITY_TIERS,
    classify_popularity,
    rank_current_candidates,
)


def _excluded_tmdb_ids(
    user_slug: str, *, include_watchlist: bool, include_watched: bool = False
) -> set[int]:
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.slug == user_slug))
        if user is None:
            raise typer.BadParameter(f"Unknown user: {user_slug}")
        conditions = []
        if not include_watched:
            conditions.append(UserMovieInteraction.watched.is_(True))
        if not include_watchlist:
            conditions.append(UserMovieInteraction.watchlisted.is_(True))
        if not conditions:
            return set()
        rows = session.scalars(
            select(Movie.tmdb_id)
            .join(UserMovieInteraction, UserMovieInteraction.movie_id == Movie.id)
            .where(
                UserMovieInteraction.user_id == user.id,
                Movie.tmdb_id.is_not(None),
                or_(*conditions),
            )
        ).all()
        return {int(value) for value in rows}


@lru_cache(maxsize=3)
def _load_shared_recommender_assets(artifact_key: str) -> tuple:
    """Load immutable large artifacts once per process for fast repeat/group scoring."""
    artifact_dir = Path(artifact_key)
    matrix, _, movie_ids, manifest = load_movielens_artifacts(artifact_dir)
    catalog = pd.read_csv(artifact_dir / manifest["files"]["catalog"])
    collaborative: LatentFactorModel = joblib.load(
        artifact_dir / "collaborative" / "latent_factor.joblib"
    )
    popularity = PopularityBaseline.fit(matrix, movie_ids)
    return catalog, movie_ids, manifest, collaborative, popularity


def warm_recommender_cache(artifact_dir: Path) -> None:
    """Warm shared read-only artifacts before concurrent profile scoring."""
    _load_shared_recommender_assets(str(artifact_dir.resolve()))


def main(
    artifact_dir: Path,
    user: str = "default",
    limit: int = 20,
    pages: int = 10,
    lookback_days: int = 1095,
    lookahead_days: int = 180,
    minimum_votes: int = 20,
    include_watchlist: bool = False,
    include_watched: bool = False,
    scope: str = "all",
    year_min: int | None = None,
    year_max: int | None = None,
    runtime_min: int | None = None,
    runtime_max: int | None = None,
    catalog_preselect: int = 250,
    minimum_movielens_ratings: int = 100,
    popularity_tier: str = "all",
    genre: str | None = None,
    metadata_category: str | None = None,
    metadata_value: str | None = None,
    metadata_filters: str | None = None,
    media_type: str = "all",
    title_query: str | None = None,
    candidate_tmdb_ids: str | None = None,
    bottom_limit: int = 5,
    max_per_primary_genre: int = 4,
    live_tmdb: bool = True,
    persist: bool = True,
    emit: bool = True,
) -> dict:
    settings = get_settings()
    if not settings.tmdb_api_key:
        raise typer.BadParameter("TMDB_API_KEY is required")
    catalog, _movie_ids, manifest, collaborative, popularity = _load_shared_recommender_assets(
        str(artifact_dir.resolve())
    )
    movielens_by_tmdb = {
        int(row.tmdb_id): int(row.movieId)
        for row in catalog[catalog["tmdb_id"].notna()].itertuples()
    }
    with SessionLocal() as session:
        personal = linked_personal_ratings(session, user, catalog)
        tmdb_personal = personal_tmdb_ratings(session, user)
        tmdb_reviews = personal_tmdb_reviews(session, user)
    if len(personal) < 2:
        raise typer.BadParameter("At least two MovieLens-linked personal ratings are required")
    # Fit this inexpensive personal layer on demand so every imported profile gets
    # its own ranking without requiring a separate training command or artifact.
    content = ContentBaseline.fit(catalog, personal)
    personal_factors = collaborative.fit_personal(personal)
    rating_interval = RatingInterval.from_evaluations(
        artifact_dir / "evaluations" / user,
        coverage=0.90,
    )
    review_policy = load_review_policy(
        settings.processed_data_dir / "review-policies" / f"{user}.json"
    )
    review_signal_scale = (
        float(review_policy.get("selected_scale") or 0.0) if review_policy.get("enabled") else 0.0
    )
    movielens_rating_counts = {
        int(movie_id): int(count)
        for movie_id, count in zip(popularity.movie_ids, popularity.counts, strict=True)
    }
    if scope not in {"all", "recent", "catalog"}:
        raise typer.BadParameter("scope must be one of: all, recent, catalog")
    if year_min is not None and year_max is not None and year_min > year_max:
        raise typer.BadParameter("year_min cannot be greater than year_max")
    if runtime_min is not None and runtime_max is not None and runtime_min > runtime_max:
        raise typer.BadParameter("runtime_min cannot be greater than runtime_max")
    if popularity_tier not in POPULARITY_TIERS:
        raise typer.BadParameter(
            f"popularity_tier must be one of: {', '.join(sorted(POPULARITY_TIERS))}"
        )
    if media_type not in {"all", "movie", "tv"}:
        raise typer.BadParameter("media_type must be one of: all, movie, tv")
    if bool(metadata_category) != bool(metadata_value):
        raise typer.BadParameter(
            "metadata_category and metadata_value must be provided together"
        )
    if metadata_category and metadata_category not in METADATA_FILTER_CATEGORIES:
        raise typer.BadParameter(f"Unsupported metadata filter: {metadata_category}")
    parsed_metadata_filters: list[dict[str, str]] = []
    if metadata_filters:
        try:
            decoded_filters = json.loads(metadata_filters)
        except json.JSONDecodeError as error:
            raise typer.BadParameter("metadata_filters must be valid JSON") from error
        if not isinstance(decoded_filters, list):
            raise typer.BadParameter("metadata_filters must be a JSON list")
        for item in decoded_filters:
            if not isinstance(item, dict):
                raise typer.BadParameter("Each metadata filter must be an object")
            category = str(item.get("category") or "").strip()
            value = str(item.get("value") or "").strip()
            if category not in METADATA_FILTER_CATEGORIES or not value:
                raise typer.BadParameter("Invalid metadata filter category or value")
            parsed_metadata_filters.append({"category": category, "value": value})
    if metadata_category and metadata_value:
        parsed_metadata_filters.append(
            {"category": metadata_category, "value": metadata_value}
        )
    excluded = _excluded_tmdb_ids(
        user,
        include_watchlist=include_watchlist,
        include_watched=include_watched,
    )

    # Every TMDB-linked MovieLens title is scored in the inexpensive first stage.
    # Rich TMDB metadata is used when cached, but is not required for eligibility.
    catalog_rows = catalog[catalog["tmdb_id"].notna()].copy()
    if year_min is not None:
        catalog_rows = catalog_rows[catalog_rows["year"] >= year_min]
    if year_max is not None:
        catalog_rows = catalog_rows[catalog_rows["year"] <= year_max]
    catalog_rows = catalog_rows[~catalog_rows["tmdb_id"].astype(int).isin(excluded)]
    catalog_candidates: dict[int, dict] = {}
    if scope in {"all", "catalog"}:
        for row in catalog_rows.itertuples():
            tmdb_id = int(row.tmdb_id)
            year = int(row.year) if pd.notna(row.year) else None
            catalog_candidates[tmdb_id] = {
                "id": tmdb_id,
                "media_type": "movie",
                "title": row.clean_title,
                "release_date": f"{year}-01-01" if year else "",
                "genres": [
                    {"name": value}
                    for value in str(row.genres).split("|")
                    if value and value != "(no genres listed)"
                ],
                "vote_average": 0.0,
                "vote_count": 0,
            }

    today = date.today()
    start = today - timedelta(days=lookback_days)
    end = today + timedelta(days=lookahead_days)
    cache_path = settings.processed_data_dir / "tmdb-rich-details.json"
    cached_raw = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    unavailable_movie_ids = {
        int(key)
        for key, value in cached_raw.items()
        if str(key).isdigit() and value.get("missing") is True
    }
    enriched = {
        int(key): value for key, value in cached_raw.items() if value.get("missing") is not True
    }
    display_cached: dict = {}
    display_cache_path = settings.processed_data_dir / "display-metadata.json"
    if display_cache_path.exists():
        try:
            display_cached = json.loads(display_cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            display_cached = {}
        for raw_id, display_details in display_cached.items():
            if not str(raw_id).isdigit() or not display_details.get("title"):
                continue
            tmdb_id = int(raw_id)
            normalized_details = dict(display_details)
            if display_details.get("media_type") == "tv" and display_details.get("id"):
                tmdb_id = -abs(int(display_details["id"]))
                normalized_details["id"] = tmdb_id
            if tmdb_id in enriched:
                enriched[tmdb_id].update(
                    {
                        key: value
                        for key, value in normalized_details.items()
                        if value is not None and key != "watch_providers"
                    }
                )
            else:
                enriched[tmdb_id] = normalized_details
    details_fetched = 0
    recent_candidates: list[dict] = []
    if live_tmdb and scope in {"all", "recent"}:
        client = TmdbClient(settings.tmdb_api_key)
        try:
            if media_type != "tv":
                for page in range(1, pages + 1):
                    response = client.discover_movies(
                        release_date_gte=start.isoformat(),
                        release_date_lte=end.isoformat(),
                        page=page,
                        minimum_votes=minimum_votes,
                    )
                    recent_candidates.extend(response.get("results", []))
                    if page >= int(response.get("total_pages") or page):
                        break
            if media_type == "tv":
                for page in range(1, pages + 1):
                    response = client.discover_tv(
                        page=page,
                        minimum_votes=minimum_votes,
                        first_air_date_gte=(f"{year_min}-01-01" if year_min else None),
                        first_air_date_lte=(f"{year_max}-12-31" if year_max else None),
                    )
                    recent_candidates.extend(
                        normalize_tv_search_result(item)
                        for item in response.get("results", [])
                    )
                    if page >= int(response.get("total_pages") or page):
                        break
            recent_fetch_ids = {
                int(item["id"]) for item in recent_candidates if item.get("id") is not None
            }
            fetched_values, details_fetched = load_or_fetch_details(
                client,
                set(tmdb_personal).union(recent_fetch_ids),
                cache_path,
            )
            enriched.update(fetched_values)
        finally:
            client.close()

    recent_ids = {
        int(item["id"])
        for item in [*recent_candidates, *enriched.values()]
        if item.get("id") is not None
        and int(item["id"]) not in movielens_by_tmdb
        and (year_min is None or (item.get("release_date") or "")[:4] >= str(year_min))
        and (year_max is None or (item.get("release_date") or "")[:4] <= str(year_max))
        and int(item["id"]) not in excluded
    }
    candidates_by_id = dict(catalog_candidates)
    if scope in {"all", "recent"}:
        for tmdb_id in recent_ids:
            if tmdb_id in enriched:
                candidates_by_id[tmdb_id] = enriched[tmdb_id]
    # Replace lightweight catalog records with richer cached data when available.
    for tmdb_id in set(candidates_by_id).intersection(enriched):
        candidates_by_id[tmdb_id] = enriched[tmdb_id]
    for raw_id, display_details in display_cached.items():
        if str(raw_id).lstrip("-").isdigit() and int(raw_id) in candidates_by_id:
            runtime = display_details.get("runtime")
            if runtime:
                candidates_by_id[int(raw_id)]["runtime"] = runtime
    candidate_ids = set(candidates_by_id)

    personal_details = {key: enriched[key] for key in tmdb_personal if key in enriched}
    rich_candidate_details = {key: enriched[key] for key in candidate_ids if key in enriched}
    model_weight_policy = select_personalized_weights(
        settings.processed_data_dir / "model-weights" / f"{user}.json",
        catalog,
        personal,
        popularity,
        collaborative,
        tmdb_details=personal_details,
        tmdb_ratings=tmdb_personal,
    )
    hybrid_weights = weights_from_policy(model_weight_policy)
    cold_start_weights = model_weight_policy["cold_start_weights"]
    rich_content_scores: dict[int, float] = {}
    metadata_matches: dict[int, tuple[str, ...]] = {}
    metadata_cautions: dict[int, tuple[str, ...]] = {}
    if len(personal_details) >= 10:
        rich_content = TmdbContentModel.fit(personal_details, tmdb_personal)
        rich_content_scores = rich_content.predict(rich_candidate_details)
        metadata_matches = {
            tmdb_id: rich_content.explanation_features(details)
            for tmdb_id, details in rich_candidate_details.items()
        }
        metadata_cautions = {
            tmdb_id: rich_content.caution_features(details)
            for tmdb_id, details in rich_candidate_details.items()
        }
    review_affinities: dict[int, float] = {}
    review_terms: dict[int, tuple[str, ...]] = {}
    if len(tmdb_reviews) >= 10:
        review_themes = ReviewThemeModel.fit(
            tmdb_reviews,
            tmdb_personal,
            {**personal_details, **rich_candidate_details},
        )
        review_affinities = review_themes.affinities(rich_candidate_details)
        review_terms = {
            tmdb_id: review_themes.explanation_terms(details)
            for tmdb_id, details in rich_candidate_details.items()
        }
    available_years = [
        int(value["release_date"][:4])
        for value in candidates_by_id.values()
        if (value.get("release_date") or "")[:4].isdigit()
    ]

    def in_popularity_tier(item: dict) -> bool:
        tmdb_id = int(item["id"])
        movie_id = movielens_by_tmdb.get(tmdb_id)
        evidence = max(
            int(item.get("vote_count") or 0),
            movielens_rating_counts.get(movie_id, 0) if movie_id else 0,
        )
        release = item.get("release_date") or ""
        year = int(release[:4]) if release[:4].isdigit() else None
        return popularity_tier == "all" or classify_popularity(year, evidence) == popularity_tier

    eligible_candidates = [item for item in candidates_by_id.values() if in_popularity_tier(item)]
    if media_type != "all":
        eligible_candidates = [
            item
            for item in eligible_candidates
            if (
                media_type == "tv"
                and (item.get("media_type") == "tv" or int(item.get("id") or 0) < 0)
            )
            or (
                media_type == "movie"
                and item.get("media_type") != "tv"
                and int(item.get("id") or 0) >= 0
                and int(item.get("id") or 0) not in unavailable_movie_ids
            )
        ]
    if runtime_min is not None or runtime_max is not None:
        eligible_candidates = [
            item
            for item in eligible_candidates
            if int(item.get("runtime") or 0) > 0
            and (runtime_min is None or int(item["runtime"]) >= runtime_min)
            and (runtime_max is None or int(item["runtime"]) <= runtime_max)
        ]
    if genre:
        normalized_genre = genre.casefold().strip()
        eligible_candidates = [
            item
            for item in eligible_candidates
            if normalized_genre
            in {
                str(value.get("name") if isinstance(value, dict) else value).casefold()
                for value in item.get("genres", [])
            }
        ]
    if parsed_metadata_filters:
        eligible_candidates = [
            item
            for item in eligible_candidates
            if all(
                matches_metadata_filter(item, selected["category"], selected["value"])
                for selected in parsed_metadata_filters
            )
        ]
    if candidate_tmdb_ids:
        requested_ids = {
            int(value.strip())
            for value in candidate_tmdb_ids.split(",")
            if value.strip().lstrip("-").isdigit()
        }
        eligible_candidates = [
            item for item in eligible_candidates if int(item["id"]) in requested_ids
        ]
    if title_query:
        normalized_query = title_query.casefold().strip()
        eligible_candidates = [
            item
            for item in eligible_candidates
            if normalized_query
            in str(item.get("title") or item.get("original_title") or "").casefold()
        ]

    ranked = rank_current_candidates(
        eligible_candidates,
        excluded_tmdb_ids=excluded,
        movielens_by_tmdb=movielens_by_tmdb,
        content=content,
        collaborative=collaborative,
        personal_factors=personal_factors,
        popularity=popularity,
        user_mean=sum(personal.values()) / len(personal),
        rich_content_scores=rich_content_scores,
        candidate_origins={
            tmdb_id: (
                "tmdb_recent+movielens_catalog"
                if tmdb_id in recent_ids and tmdb_id in catalog_candidates
                else "tmdb_recent"
                if tmdb_id in recent_ids
                else "movielens_catalog"
            )
            for tmdb_id in candidate_ids
        },
        review_affinities=review_affinities,
        review_terms=review_terms,
        metadata_matches=metadata_matches,
        metadata_cautions=metadata_cautions,
        movielens_rating_counts=movielens_rating_counts,
        limit=limit,
        max_per_primary_genre=max_per_primary_genre,
        rating_interval=rating_interval,
        review_signal_scale=review_signal_scale,
        hybrid_weights=hybrid_weights,
        cold_start_weights=cold_start_weights,
    )
    lowest_ranked = (
        rank_current_candidates(
            eligible_candidates,
            excluded_tmdb_ids=excluded,
            movielens_by_tmdb=movielens_by_tmdb,
            content=content,
            collaborative=collaborative,
            personal_factors=personal_factors,
            popularity=popularity,
            user_mean=sum(personal.values()) / len(personal),
            rich_content_scores=rich_content_scores,
            candidate_origins={
                tmdb_id: (
                    "tmdb_recent+movielens_catalog"
                    if tmdb_id in recent_ids and tmdb_id in catalog_candidates
                    else "tmdb_recent"
                    if tmdb_id in recent_ids
                    else "movielens_catalog"
                )
                for tmdb_id in candidate_ids
            },
            review_affinities=review_affinities,
            review_terms=review_terms,
            metadata_matches=metadata_matches,
            metadata_cautions=metadata_cautions,
            movielens_rating_counts=movielens_rating_counts,
            limit=bottom_limit + limit,
            max_per_primary_genre=bottom_limit + limit,
            descending=False,
            rating_interval=rating_interval,
            review_signal_scale=review_signal_scale,
            hybrid_weights=hybrid_weights,
            cold_start_weights=cold_start_weights,
        )
        if bottom_limit > 0
        else []
    )
    top_tmdb_ids = {item.tmdb_id for item in ranked}
    lowest_ranked = [
        item for item in lowest_ranked if item.tmdb_id not in top_tmdb_ids
    ][:bottom_limit]
    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user": user,
        "scope": scope,
        "popularity_tier": popularity_tier,
        "genre_filter": genre,
        "metadata_filter": {
            "category": metadata_category,
            "value": metadata_value,
        },
        "metadata_filters": parsed_metadata_filters,
        "media_type_filter": media_type,
        "year_filter": {"minimum": year_min, "maximum": year_max},
        "runtime_filter": {"minimum": runtime_min, "maximum": runtime_max},
        "recent_candidate_window": {"from": start.isoformat(), "through": end.isoformat()},
        "recent_candidates": len(recent_ids),
        "catalog_candidates": len(catalog_candidates),
        "candidate_universe": len(candidate_ids),
        "candidates_considered": len(eligible_candidates),
        "available_candidate_years": {
            "minimum": min(available_years) if available_years else None,
            "maximum": max(available_years) if available_years else None,
        },
        "movielens_linked_personal_ratings": len(personal),
        "tmdb_enriched_personal_ratings": len(personal_details),
        "personal_reviews_used": len(tmdb_reviews),
        "review_signal_affects_score": bool(review_signal_scale),
        "review_signal_policy": review_policy,
        "model_weight_policy": model_weight_policy,
        "rating_interval": {
            "coverage": rating_interval.coverage,
            "samples": rating_interval.samples,
            "method": rating_interval.method,
            "lower_offset": round(rating_interval.lower_offset, 4),
            "upper_offset": round(rating_interval.upper_offset, 4),
        },
        "tmdb_enriched_candidates": len(rich_candidate_details),
        "lightweight_catalog_candidates": len(candidate_ids) - len(rich_candidate_details),
        "unavailable_candidate_details": 0,
        "tmdb_details_fetched": details_fetched,
        "ranking_metrics": compute_ranking_metrics(
            ranked,
            candidates_considered=len(eligible_candidates),
            popularity=popularity,
            total_users=int(manifest["users"]),
        ),
        "recommendations": [item.to_dict() for item in ranked],
        "lowest_recommendations": [
            {**item.to_dict(), "rank": index + 1}
            for index, item in enumerate(lowest_ranked)
        ],
    }
    output_dir = artifact_dir / "recommendations" / user
    target = output_dir / f"{scope}.json"
    if persist:
        output_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(output, indent=2), encoding="utf-8")
    if emit:
        typer.echo(json.dumps({"report": str(target), **output}, indent=2))
    return output


if __name__ == "__main__":
    typer.run(main)
