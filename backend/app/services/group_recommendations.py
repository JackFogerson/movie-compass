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
from recommendation.ranking.current_catalog import humanize_metadata_matches


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
    media_type: str,
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
        media_type=media_type,
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
    media_type: str,
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
        media_type=media_type,
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


def _shared_matches(individual: list[dict], field: str) -> tuple[str, ...]:
    if not individual:
        return ()
    common = set(individual[0].get(field, ()))
    for item in individual[1:]:
        common.intersection_update(item.get(field, ()))
    return tuple(value for value in individual[0].get(field, ()) if value in common)


def _group_like_explanations(individual: list[dict]) -> list[str]:
    shared = _shared_matches(individual, "positive_matches")
    if shared:
        return [
            f"Everyone's ratings point to the same strengths here: "
            f"{humanize_metadata_matches(shared)} have worked well for every profile."
        ]

    personal_hooks = []
    for item in individual:
        matches = tuple(item.get("positive_matches", ()))[:2]
        if matches:
            name = item.get("display_name", item["user"])
            personal_hooks.append(f"{name} tends to enjoy {humanize_metadata_matches(matches)}")
    if personal_hooks:
        return [
            "There is no single recorded theme shared by every profile, but the movie has "
            f"different hooks for the group: {'; '.join(personal_hooks)}."
        ]
    return [
        "The model does not have one specific genre or theme shared by every profile; its "
        "appeal comes from the overall pattern of each person's past ratings."
    ]


def _caution_clause(match: str) -> str:
    kind, _, value = match.partition(": ")
    value = value.strip()
    if kind == "genre":
        return f"{value.casefold()} films have often received lower ratings"
    if kind == "story/theme":
        return f"stories centered on {value} have been less reliable"
    if kind == "director":
        return f"{value.title()}'s films have been a mixed fit"
    if kind == "cast member":
        return f"films featuring {value.title()} have been less consistent"
    if kind == "release era":
        return f"movies from the {value} have usually scored lower"
    if kind == "original language":
        return f"{value.upper()}-language films have been less predictable"
    return f"{value or match} has been a weaker signal"


def _group_caution_explanations(individual: list[dict]) -> list[str]:
    shared = _shared_matches(individual, "caution_matches")
    explanations: list[str] = []
    if shared:
        explanations.append(
            f"The clearest shared concern is {humanize_metadata_matches(shared)}: those "
            "elements have tended to receive lower ratings from everyone in the group."
        )
    for item in individual:
        matches = tuple(item.get("caution_matches", ()))[:2]
        name = item.get("display_name", item["user"])
        if matches:
            explanations.append(
                f"For {name}, "
                + " and ".join(_caution_clause(match) for match in matches)
                + "."
            )
        elif item.get("cautions"):
            caution = str(item["cautions"][0]).removeprefix("One possible concern: ")
            caution = caution.replace("you have", f"{name} has").replace(
                "for you", f"for {name}"
            )
            explanations.append(f"For {name}, {caution}")
    if not explanations:
        explanations.append(
            "No strong shared warning appears in the group's rating histories. The remaining "
            "risk is that the movie's execution may not deliver on the traits the model expects."
        )
    return explanations


def _group_reason(individual: list[dict]) -> str:
    scores = [float(item["expected_rating"]) for item in individual]
    minimum = min(scores)
    maximum = max(scores)
    opening = _group_like_explanations(individual)[0]
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


def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _featured_divergence_reason(individual: list[dict], user: str, rank: int) -> str:
    featured = next(item for item in individual if item["user"] == user)
    weakest = min(individual, key=lambda item: item["expected_rating"])
    featured_name = featured.get("display_name", featured["user"])
    weakest_name = weakest.get("display_name", weakest["user"])
    gap = float(featured["expected_rating"]) - float(weakest["expected_rating"])
    if rank == 1:
        return (
            f"This is {featured_name}'s biggest enthusiast split. They are predicted at "
            f"{featured['expected_rating']:.2f}/5 while {weakest_name} is at "
            f"{weakest['expected_rating']:.2f}/5, a {gap:.2f}-point gap."
        )
    if gap > 0:
        return (
            f"No available movie puts {featured_name} first, so this is their best "
            f"{_ordinal(rank)}-most-enthusiastic split. They are predicted at "
            f"{featured['expected_rating']:.2f}/5 versus {weakest_name} at "
            f"{weakest['expected_rating']:.2f}/5, a {gap:.2f}-point gap."
        )
    strongest = max(individual, key=lambda item: item["expected_rating"])
    strongest_name = strongest.get("display_name", strongest["user"])
    return (
        f"No available movie places {featured_name} above another group member. This is "
        f"their closest fallback: {featured_name} is predicted at "
        f"{featured['expected_rating']:.2f}/5 while {strongest_name} is at "
        f"{strongest['expected_rating']:.2f}/5."
    )


def _lowest_group_reason(individual: list[dict]) -> str:
    scores = [float(item["expected_rating"]) for item in individual]
    weakest = min(individual, key=lambda item: item["expected_rating"])
    strongest = max(individual, key=lambda item: item["expected_rating"])
    appeal = _group_like_explanations(individual)[0]
    return (
        f"{appeal} Even with that potential appeal, this falls near the bottom because "
        "the group average is only "
        f"{sum(scores) / len(scores):.2f}/5. "
        f"{weakest.get('display_name', weakest['user'])} is the most cautious at "
        f"{weakest['expected_rating']:.2f}/5, and even "
        f"{strongest.get('display_name', strongest['user'])}'s prediction reaches only "
        f"{strongest['expected_rating']:.2f}/5."
    )


def _per_person_divisive_rows(rows: list[dict], users: list[str]) -> list[dict]:
    """Choose one split per person, falling back through enthusiasm ranks."""
    selected: list[dict] = []
    for user in users:
        candidates: list[tuple[int, float, dict]] = []
        for row in rows:
            scores = {
                item["user"]: float(item["expected_rating"])
                for item in row["individual_scores"]
            }
            other_scores = [score for candidate, score in scores.items() if candidate != user]
            if not other_scores:
                continue
            rank = 1 + sum(score > scores[user] for score in other_scores)
            gap_above_lowest = scores[user] - min(scores.values())
            candidates.append((rank, gap_above_lowest, row))
        if not candidates:
            continue
        best_rank = min(item[0] for item in candidates)
        best_ranked = [item for item in candidates if item[0] == best_rank]
        _, _, winner = max(
            best_ranked,
            key=lambda item: (
                item[1],
                item[2]["group_spread"],
                next(
                    score["expected_rating"]
                    for score in item[2]["individual_scores"]
                    if score["user"] == user
                ),
            ),
        )
        featured = dict(winner)
        featured["featured_enthusiast"] = user
        featured["featured_enthusiast_display_name"] = next(
            item.get("display_name", user)
            for item in featured["individual_scores"]
            if item["user"] == user
        )
        featured["featured_enthusiasm_rank"] = best_rank
        featured["featured_enthusiasm_label"] = (
            "most enthusiastic"
            if best_rank == 1
            else f"{_ordinal(best_rank)} most enthusiastic"
        )
        selected.append(featured)
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
    media_type: str = "all",
    title_query: str | None = None,
    candidate_tmdb_ids: str | None = None,
    include_watched: bool = False,
    shortlist_per_user: int = 500,
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
    primed_reports: dict[str, dict] = {}
    if media_type == "tv" and not exact_search:
        first_user = normalized[0]
        primed_reports[first_user] = generate_recommendations(
            artifact_dir,
            user=first_user,
            limit=shortlist_per_user,
            bottom_limit=max(50, bottom_limit * 20),
            max_per_primary_genre=20,
            scope="all",
            year_min=year_min,
            year_max=year_max,
            runtime_min=runtime_min,
            runtime_max=runtime_max,
            popularity_tier=popularity,
            genre=genre,
            media_type=media_type,
            include_watched=True,
            live_tmdb=True,
            persist=False,
            emit=False,
        )

    def initial_score(user: str) -> tuple[str, dict]:
        if user in primed_reports:
            return user, primed_reports[user]
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
            media_type,
            title_query,
            candidate_tmdb_ids,
            True,
        )

    with ThreadPoolExecutor(max_workers=len(normalized)) as executor:
        initial_reports = dict(executor.map(initial_score, normalized))

    catalog_screened_by_profile = {
        user: int(report.get("candidate_universe", 0))
        for user, report in initial_reports.items()
    }
    catalog_candidates_screened = max(catalog_screened_by_profile.values(), default=0)

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
            "catalog_candidates_screened": catalog_candidates_screened,
            "catalog_screened_by_profile": catalog_screened_by_profile,
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
                media_type,
                True,
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
                    "positive_matches": movie.get("metadata_matches", []),
                    "caution_matches": movie.get("caution_matches", []),
                    "evidence_level": movie["ranking_expectation"]["evidence_level"],
                }
            )
        values = np.array([item["expected_rating"] for item in individual], dtype=float)
        average = float(values.mean())
        minimum = float(values.min())
        disagreement = float(values.std())
        watched_by = [user for user in normalized if tmdb_id in watched_by_user[user]]
        watched_fraction = len(watched_by) / len(normalized)
        if watched_fraction == 1.0 and not include_watched:
            continue
        rewatch_penalty = 0.2 * watched_fraction
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
                "watched_count": len(watched_by),
                "watched_by": watched_by,
                "individual_scores": individual,
                "group_reason": reason,
                "why_you_may_like_it": _group_like_explanations(individual),
                "why_you_may_not_like_it": _group_caution_explanations(individual),
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
        low["why_you_may_like_it"] = _group_like_explanations(low["individual_scores"])
        low["why_you_may_not_like_it"] = _group_caution_explanations(
            low["individual_scores"]
        )
        lowest.append(low)
        if len(lowest) >= bottom_limit:
            break
    most_divisive = []
    unwatched_split_rows = [row for row in rows if not row["watched_by"]]
    for row in _per_person_divisive_rows(unwatched_split_rows, normalized):
        divisive = dict(row)
        divisive["rank"] = len(most_divisive) + 1
        divisive["group_reason"] = _featured_divergence_reason(
            divisive["individual_scores"],
            divisive["featured_enthusiast"],
            divisive["featured_enthusiasm_rank"],
        )
        most_divisive.append(divisive)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "users": normalized,
        "strategy": "balanced_average_and_minimum",
        "catalog_candidates_screened": catalog_candidates_screened,
        "catalog_screened_by_profile": catalog_screened_by_profile,
        "candidate_union": len(candidate_ids),
        "eligible_for_everyone": len(rows),
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
