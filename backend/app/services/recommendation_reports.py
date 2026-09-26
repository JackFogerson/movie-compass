from __future__ import annotations

import json
import re
from pathlib import Path

VALID_SCOPES = {"all", "recent", "catalog"}
VALID_MEDIA_TYPES = {"all", "movie", "tv"}
VALID_USER = re.compile(r"^[A-Za-z0-9_-]+$")


class RecommendationReportNotFound(FileNotFoundError):
    pass


def _latest_artifact(artifacts_root: Path) -> Path:
    candidates = [
        path
        for path in artifacts_root.glob("movielens-32m-*")
        if path.is_dir() and (path / "manifest.json").is_file()
    ]
    if not candidates:
        raise RecommendationReportNotFound("No MovieLens artifact is available")
    return max(candidates, key=lambda path: (path / "manifest.json").stat().st_mtime)


def load_recommendation_report(
    artifacts_root: Path,
    user: str,
    *,
    scope: str = "all",
    year_min: int | None = None,
    year_max: int | None = None,
    runtime_min: int | None = None,
    runtime_max: int | None = None,
    genre: str | None = None,
    media_type: str = "all",
    limit: int = 20,
) -> dict:
    if not VALID_USER.fullmatch(user):
        raise ValueError("Invalid user slug")
    if scope not in VALID_SCOPES:
        raise ValueError(f"Invalid scope: {scope}")
    if year_min is not None and year_max is not None and year_min > year_max:
        raise ValueError("year_min cannot be greater than year_max")
    if runtime_min is not None and runtime_max is not None and runtime_min > runtime_max:
        raise ValueError("runtime_min cannot be greater than runtime_max")
    if media_type not in VALID_MEDIA_TYPES:
        raise ValueError(f"Invalid media type: {media_type}")
    artifact = _latest_artifact(artifacts_root)
    target = artifact / "recommendations" / user / f"{scope}.json"
    if not target.is_file():
        raise RecommendationReportNotFound(
            f"No precomputed {scope} recommendations are available for {user}"
        )
    report = json.loads(target.read_text(encoding="utf-8"))
    source_recommendations = report.get("recommendations", [])
    normalized_genre = genre.casefold().strip() if genre else None

    def matches(item: dict) -> bool:
        return (
            (year_min is None or item.get("year") is not None and item["year"] >= year_min)
            and (year_max is None or item.get("year") is not None and item["year"] <= year_max)
            and (
                runtime_min is None
                or item.get("runtime") is not None
                and item["runtime"] >= runtime_min
            )
            and (
                runtime_max is None
                or item.get("runtime") is not None
                and item["runtime"] <= runtime_max
            )
            and (
                normalized_genre is None
                or normalized_genre in {str(value).casefold() for value in item.get("genres", [])}
            )
            and (
                media_type == "all"
                or (media_type == "tv") == (int(item.get("tmdb_id") or 0) < 0)
            )
        )

    filtered = [item for item in source_recommendations if matches(item)][:limit]
    lowest = [item for item in report.get("lowest_recommendations", []) if matches(item)][:5]
    ranking_metrics = report.pop("ranking_metrics", None)
    return {
        **report,
        "source_ranking_metrics": ranking_metrics,
        "api_filter": {
            "scope": scope,
            "year_min": year_min,
            "year_max": year_max,
            "runtime_min": runtime_min,
            "runtime_max": runtime_max,
            "genre": genre,
            "media_type": media_type,
            "limit": limit,
            "source_recommendations": len(source_recommendations),
            "returned": len(filtered),
        },
        "recommendations": filtered,
        "lowest_recommendations": lowest,
    }


def available_recommendation_scopes(artifacts_root: Path, user: str) -> dict:
    if not VALID_USER.fullmatch(user):
        raise ValueError("Invalid user slug")
    artifact = _latest_artifact(artifacts_root)
    directory = artifact / "recommendations" / user
    scopes = []
    for scope in sorted(VALID_SCOPES):
        target = directory / f"{scope}.json"
        if not target.is_file():
            continue
        report = json.loads(target.read_text(encoding="utf-8"))
        scopes.append(
            {
                "scope": scope,
                "generated_at": report.get("generated_at"),
                "available_candidate_years": report.get("available_candidate_years"),
                "recommendations": len(report.get("recommendations", [])),
            }
        )
    return {"user": user, "artifact": artifact.name, "scopes": scopes}
