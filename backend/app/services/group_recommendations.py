from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
from sqlalchemy import select

from app.cli.recommend import main as generate_recommendations
from app.cli.recommend import warm_recommender_cache
from app.db.models import Movie, User, UserMovieInteraction
from app.db.session import SessionLocal
from app.services.recommendation_reports import VALID_USER


@lru_cache(maxsize=64)
def _cached_profile_shortlist(
    artifact_key: str,
    user: str,
    shortlist_limit: int,
    bottom_shortlist_limit: int,
    year_min: int | None,
    year_max: int | None,
    runtime_min: int | None,
    runtime_max: int | None,
    popularity: str,
    genre: str | None,
    title_query: str | None,
    candidate_tmdb_ids: str | None,
    include_watched: bool,
) -> dict:
    return generate_recommendations(
        Path(artifact_key),
        user=user,
        limit=shortlist_limit,
        bottom_limit=bottom_shortlist_limit,
        max_per_primary_genre=20,
        scope="all",
        year_min=year_min,
        year_max=year_max,
        runtime_min=runtime_min,
        runtime_max=runtime_max,
        popularity_tier=popularity,
        genre=genre,
        title_query=title_query,
        candidate_tmdb_ids=candidate_tmdb_ids,
        include_watched=include_watched,
        live_tmdb=False,
        persist=False,
        emit=False,
    )


@lru_cache(maxsize=64)
def _cached_candidate_scores(
    artifact_key: str,
    user: str,
    candidate_tmdb_ids: str,
    year_min: int | None,
    year_max: int | None,
    runtime_min: int | None,
    runtime_max: int | None,
    popularity: str,
    genre: str | None,
    include_watched: bool,
) -> dict:
    candidate_count = candidate_tmdb_ids.count(",") + 1
    return generate_recommendations(
        Path(artifact_key),
        user=user,
        limit=candidate_count,
        bottom_limit=0,
        max_per_primary_genre=candidate_count,
        scope="all",
        year_min=year_min,
        year_max=year_max,
        runtime_min=runtime_min,
        runtime_max=runtime_max,
        popularity_tier=popularity,
        genre=genre,
        candidate_tmdb_ids=candidate_tmdb_ids,
        include_watched=include_watched,
        live_tmdb=False,
        persist=False,
        emit=False,
    )


def clear_group_recommendation_cache() -> None:
    """Invalidate profile shortlists after an import changes local taste data."""
    _cached_profile_shortlist.cache_clear()
    _cached_candidate_scores.cache_clear()


def _group_reason(individual: list[dict]) -> str:
    scores = [float(item["expected_rating"]) for item in individual]
    minimum = min(scores)
    maximum = max(scores)
    spread = maximum - minimum
    if minimum >= 4.0:
        opening = "This is a rare across-the-board match: everyone is predicted to rate it highly."
    elif spread <= 0.4:
        opening = (
            "Everyone's prediction lands in a tight range, making this a balanced group choice."
        )
    elif minimum >= 3.25:
        opening = "It has a strong group average without leaving anyone with a weak prediction."
    else:
        opening = "The overall fit is promising, though one person's prediction is more cautious."
    strongest = max(individual, key=lambda item: item["expected_rating"])
    return (
        f"{opening} Scores run from {minimum:.2f} to {maximum:.2f}; "
        f"{strongest.get('display_name', strongest['user'])} is the most enthusiastic match."
    )


def _watched_by_user(users: list[str]) -> dict[str, set[int]]:
    watched = {user: set() for user in users}
    with SessionLocal() as session:
        rows = session.execute(
            select(User.slug, Movie.tmdb_id)
            .join(UserMovieInteraction, UserMovieInteraction.user_id == User.id)
            .join(Movie, Movie.id == UserMovieInteraction.movie_id)
            .where(
                User.slug.in_(users),
                UserMovieInteraction.watched.is_(True),
                Movie.tmdb_id.is_not(None),
            )
        ).all()
    for user, tmdb_id in rows:
        watched[str(user)].add(int(tmdb_id))
    return watched


def _display_names(users: list[str]) -> dict[str, str]:
    with SessionLocal() as session:
        rows = session.execute(
            select(User.slug, User.display_name).where(User.slug.in_(users))
        ).all()
    return {str(slug): str(display_name) for slug, display_name in rows}


def _divergence_reason(individual: list[dict]) -> str:
    strongest = max(individual, key=lambda item: item["expected_rating"])
    weakest = min(individual, key=lambda item: item["expected_rating"])
    spread = float(strongest["expected_rating"]) - float(weakest["expected_rating"])
    return (
        f"This is a taste-split movie: {strongest.get('display_name', strongest['user'])} "
        f"is predicted at {strongest['expected_rating']:.2f}/5 while "
        f"{weakest.get('display_name', weakest['user'])} is at "
        f"{weakest['expected_rating']:.2f}/5, a {spread:.2f}-point gap."
    )


def _lowest_group_reason(individual: list[dict]) -> str:
    scores = [float(item["expected_rating"]) for item in individual]
    weakest = min(individual, key=lambda item: item["expected_rating"])
    strongest = max(individual, key=lambda item: item["expected_rating"])
    return (
        f"This falls near the bottom because the group average is only "
        f"{sum(scores) / len(scores):.2f}/5. "
        f"{weakest.get('display_name', weakest['user'])} is the most cautious at "
        f"{weakest['expected_rating']:.2f}/5, and even "
        f"{strongest.get('display_name', strongest['user'])}'s prediction reaches only "
        f"{strongest['expected_rating']:.2f}/5."
    )


def _balanced_divisive_rows(rows: list[dict], users: list[str], limit: int) -> list[dict]:
    ranked = sorted(rows, key=lambda item: item["group_spread"], reverse=True)
    by_enthusiast = {user: [] for user in users}
    for row in ranked:
        strongest = max(row["individual_scores"], key=lambda item: item["expected_rating"])["user"]
        by_enthusiast[str(strongest)].append(row)
    selected: list[dict] = []
    used: set[int] = set()
    while len(selected) < limit:
        progressed = False
        for user in users:
            candidates = by_enthusiast[user]
            while candidates and int(candidates[0]["tmdb_id"]) in used:
                candidates.pop(0)
            if not candidates:
                continue
            row = candidates.pop(0)
            selected.append(row)
            used.add(int(row["tmdb_id"]))
            progressed = True
            if len(selected) >= limit:
                break
        if not progressed:
            break
    for row in ranked:
        if len(selected) >= limit:
            break
        if int(row["tmdb_id"]) not in used:
            selected.append(row)
            used.add(int(row["tmdb_id"]))
    return selected


def generate_group_recommendations(
    artifact_dir: Path,
    users: list[str],
    *,
    limit: int = 20,
    year_min: int | None = None,
    year_max: int | None = None,
    runtime_min: int | None = None,
    runtime_max: int | None = None,
    popularity: str = "all",
    genre: str | None = None,
    title_query: str | None = None,
    candidate_tmdb_ids: str | None = None,
    include_watched: bool = False,
    shortlist_per_user: int = 200,
    bottom_limit: int = 5,
    divisive_limit: int = 5,
) -> dict:
    normalized = [value.strip() for value in users if value.strip()]
    if not 2 <= len(normalized) <= 4:
        raise ValueError("Group recommendations require two to four profiles")
    if len(set(normalized)) != len(normalized):
        raise ValueError("Each group profile must be different")
    if any(not VALID_USER.fullmatch(value) for value in normalized):
        raise ValueError("Invalid profile name")

    if artifact_dir.exists():
        warm_recommender_cache(artifact_dir)
    watched_by_user = _watched_by_user(normalized)
    display_names = _display_names(normalized)
    exact_search = bool(title_query or candidate_tmdb_ids)

    def initial_score(user: str) -> tuple[str, dict]:
        return user, _cached_profile_shortlist(
            str(artifact_dir.resolve()),
            user,
            25 if exact_search else shortlist_per_user,
            0 if exact_search else max(50, bottom_limit * 20),
            year_min,
            year_max,
            runtime_min,
            runtime_max,
            popularity,
            genre,
            title_query,
            candidate_tmdb_ids,
            include_watched,
        )

    with ThreadPoolExecutor(max_workers=len(normalized)) as executor:
        initial_reports = dict(executor.map(initial_score, normalized))

    candidate_ids: set[int] = set()
    for shortlist in initial_reports.values():
        candidate_ids.update(int(item["tmdb_id"]) for item in shortlist["recommendations"])
        candidate_ids.update(
            int(item["tmdb_id"]) for item in shortlist.get("lowest_recommendations", [])
        )
    if not candidate_ids:
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "users": normalized,
            "candidate_union": 0,
            "eligible_for_everyone": 0,
            "recommendations": [],
            "lowest_recommendations": [],
            "most_divisive": [],
            "include_watched": include_watched,
        }

    initial_ids = {
        user: {
            int(item["tmdb_id"])
            for item in [
                *report["recommendations"],
                *report.get("lowest_recommendations", []),
            ]
        }
        for user, report in initial_reports.items()
    }
    shared_shortlist = set.intersection(*initial_ids.values())
    used_shared_shortlist = bool(title_query or candidate_tmdb_ids)

    if used_shared_shortlist:
        scores_by_user = {
            user: {
                int(item["tmdb_id"]): item
                for item in [
                    *report["recommendations"],
                    *report.get("lowest_recommendations", []),
                ]
                if int(item["tmdb_id"]) in shared_shortlist
            }
            for user, report in initial_reports.items()
        }
    else:
        requested = ",".join(str(value) for value in sorted(candidate_ids))

        def final_score(user: str) -> tuple[str, dict]:
            return user, _cached_candidate_scores(
                str(artifact_dir.resolve()),
                user,
                requested,
                year_min,
                year_max,
                runtime_min,
                runtime_max,
                popularity,
                genre,
                include_watched,
            )

        with ThreadPoolExecutor(max_workers=len(normalized)) as executor:
            final_reports = dict(executor.map(final_score, normalized))
        scores_by_user = {
            user: {int(item["tmdb_id"]): item for item in report["recommendations"]}
            for user, report in final_reports.items()
        }

    common_ids = set.intersection(*(set(values) for values in scores_by_user.values()))
    rows: list[dict] = []
    for tmdb_id in common_ids:
        individual = []
        for user in normalized:
            movie = scores_by_user[user][tmdb_id]
            uncertainty = movie["rating_uncertainty"]
            individual.append(
                {
                    "user": user,
                    "display_name": display_names.get(user, user),
                    "expected_rating": movie["expected_rating"],
                    "plausible_minimum": uncertainty["plausible_minimum"],
                    "plausible_maximum": uncertainty["plausible_maximum"],
                    "reason": movie["ranking_expectation"]["reason"],
                    "cautions": movie.get("why_you_may_not_like_it", []),
                    "evidence_level": movie["ranking_expectation"]["evidence_level"],
                }
            )
        values = np.array([item["expected_rating"] for item in individual], dtype=float)
        average = float(values.mean())
        minimum = float(values.min())
        disagreement = float(values.std())
        watched_by = [user for user in normalized if tmdb_id in watched_by_user[user]]
        watched_fraction = len(watched_by) / len(normalized)
        rewatch_penalty = 0.2 * watched_fraction if include_watched else 0.0
        unpenalized_group_score = 0.6 * average + 0.4 * minimum - 0.1 * disagreement
        group_score = float(np.clip(unpenalized_group_score - rewatch_penalty, 0.5, 5.0))
        base = dict(scores_by_user[normalized[0]][tmdb_id])
        reason = _group_reason(individual)
        if watched_by:
            reason += (
                f" {len(watched_by)} of {len(normalized)} have seen it; a small "
                f"{rewatch_penalty:.2f}-point rewatch penalty keeps new discoveries favored."
            )
        base.update(
            {
                "group_score": round(group_score, 4),
                "expected_rating": round(group_score, 4),
                "group_average": round(average, 4),
                "group_minimum": round(minimum, 4),
                "group_disagreement": round(disagreement, 4),
                "group_spread": round(float(values.max() - values.min()), 4),
                "unpenalized_group_score": round(unpenalized_group_score, 4),
                "rewatch_penalty": round(rewatch_penalty, 4),
                "watched_fraction": round(watched_fraction, 4),
                "watched_by": watched_by,
                "individual_scores": individual,
                "group_reason": reason,
            }
        )
        rows.append(base)

    rows.sort(key=lambda item: item["group_score"], reverse=True)
    selected: list[dict] = []
    primary_genres: dict[str, int] = {}
    for row in rows:
        primary = row.get("genres", ["Unknown"])[0] if row.get("genres") else "Unknown"
        if primary_genres.get(primary, 0) >= 4:
            continue
        primary_genres[primary] = primary_genres.get(primary, 0) + 1
        row["rank"] = len(selected) + 1
        selected.append(row)
        if len(selected) >= limit:
            break
    lowest = []
    for row in reversed(rows):
        if row["tmdb_id"] in {item["tmdb_id"] for item in selected}:
            continue
        low = dict(row)
        low["rank"] = len(lowest) + 1
        low["group_reason"] = _lowest_group_reason(low["individual_scores"])
        low["why_you_may_not_like_it"] = [
            f"{item.get('display_name', item['user'])}: {item['cautions'][0]}"
            for item in low["individual_scores"]
            if item.get("cautions")
        ]
        lowest.append(low)
        if len(lowest) >= bottom_limit:
            break
    most_divisive = []
    for row in _balanced_divisive_rows(rows, normalized, divisive_limit):
        divisive = dict(row)
        divisive["rank"] = len(most_divisive) + 1
        divisive["group_reason"] = _divergence_reason(divisive["individual_scores"])
        most_divisive.append(divisive)
        if len(most_divisive) >= divisive_limit:
            break
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "users": normalized,
        "strategy": "balanced_average_and_minimum",
        "candidate_union": len(candidate_ids),
        "eligible_for_everyone": len(common_ids),
        "scoring_passes": 1 if used_shared_shortlist else 2,
        "year_filter": {"minimum": year_min, "maximum": year_max},
        "runtime_filter": {"minimum": runtime_min, "maximum": runtime_max},
        "popularity_tier": popularity,
        "genre_filter": genre,
        "title_query": title_query,
        "include_watched": include_watched,
        "rewatch_penalty_maximum": 0.2,
        "recommendations": selected,
        "lowest_recommendations": lowest,
        "most_divisive": most_divisive,
    }
