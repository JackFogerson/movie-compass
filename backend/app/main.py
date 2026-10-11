import csv
import gzip
import io
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from shutil import rmtree
from statistics import median
from tempfile import TemporaryDirectory
from typing import Annotated

import typer
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from tenacity import RetryError

from app.cli.recommend import main as generate_recommendations
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import ImportMapping, ImportRun, Movie, User, UserMovieInteraction
from app.db.session import SessionLocal
from app.services.display_metadata import enrich_display_metadata
from app.services.group_recommendations import (
    clear_group_recommendation_cache,
    generate_group_recommendations,
)
from app.services.letterboxd_import import import_letterboxd_archive
from app.services.local_catalog_mapping import map_pending_from_artifact
from app.services.profile_accuracy import profile_accuracy as evaluate_profile_accuracy
from app.services.profile_export import build_profile_archive, restore_profile_archive
from app.services.profile_stats import (
    LANGUAGE_NAMES,
    build_metadata_filter_index,
    build_public_opinion_splits,
    build_taste_breakdown,
    category_label_matches,
    metadata_filter_options,
    metadata_match_stat_target,
    movie_category_labels,
)
from app.services.recommendation_reports import (
    RecommendationReportNotFound,
    _latest_artifact,
    available_recommendation_scopes,
    load_recommendation_report,
)
from app.services.review_policy import load_review_policy, refresh_review_policy
from app.services.tmdb_mapping import map_pending_letterboxd, resolve_letterboxd_links
from ingestion.letterboxd.parser import normalize_title
from ingestion.tmdb.client import (
    TmdbClient,
    TmdbError,
    is_tv_catalog_id,
    normalize_tv_details,
    normalize_tv_search_result,
    rank_title_search_results,
    tv_catalog_id,
)
from ingestion.tmdb.daily_export import load_catalog_summary
from ingestion.tmdb.details_cache import load_or_fetch_details, merge_discovery_results
from recommendation.ranking.current_catalog import TMDB_GENRES

settings = get_settings()
configure_logging(settings.log_level)
app = FastAPI(title="Personal Movie Recommender", version="0.1.0")
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

TV_GENRES = {
    10759: "Action & Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    10762: "Kids",
    9648: "Mystery",
    10763: "News",
    10764: "Reality",
    10765: "Sci-Fi & Fantasy",
    10766: "Soap",
    10767: "Talk",
    10768: "War & Politics",
    37: "Western",
}
DISCOVERY_MAX_PAGES = 500


class MetadataFilterRequest(BaseModel):
    category: str = Field(max_length=30)
    value: str = Field(min_length=1, max_length=200)


class GroupRecommendationRequest(BaseModel):
    users: list[str] = Field(min_length=2, max_length=4)
    year_min: int | None = Field(default=None, ge=1870, le=2200)
    year_max: int | None = Field(default=None, ge=1870, le=2200)
    runtime_min: int | None = Field(default=None, ge=1, le=600)
    runtime_max: int | None = Field(default=None, ge=1, le=600)
    popularity: str = "all"
    genre: str | None = Field(default=None, max_length=60)
    metadata_category: str | None = Field(default=None, max_length=30)
    metadata_value: str | None = Field(default=None, max_length=200)
    metadata_filters: list[MetadataFilterRequest] = Field(default_factory=list, max_length=10)
    title_filter: str | None = Field(default=None, max_length=120)
    certification: str | None = Field(default=None, max_length=20)
    availability: str = Field(default="all", pattern=r"^(all|listed|subscription|free|rent_buy)$")
    media_type: str = Field(default="movie", pattern=r"^(all|movie|tv)$")
    country: str = Field(default="US", pattern=r"^[A-Z]{2}$")
    include_watched: bool = False
    exclude_any_watched: bool = False
    limit: int = Field(default=20, ge=1, le=30)


class GroupMovieSearchRequest(GroupRecommendationRequest):
    query: str = Field(min_length=2, max_length=120)
    year: int | None = Field(default=None, ge=1870, le=2200)


class ProfileUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


class ProfileDeleteRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=100)


class ManualRatingRequest(BaseModel):
    tmdb_id: int
    title: str = Field(min_length=1, max_length=500)
    year: int | None = Field(default=None, ge=1870, le=2200)
    rating: float = Field(ge=0.5, le=5.0, multiple_of=0.5)
    review_text: str | None = Field(default=None, max_length=20_000)


def _with_display_metadata(report: dict, country: str) -> dict:
    return enrich_display_metadata(
        report,
        api_key=settings.tmdb_api_key,
        cache_path=settings.processed_data_dir / "display-metadata.json",
        country=country,
    )


def _load_profile_detail_cache() -> dict[str, dict]:
    """Merge model metadata with display-only fields such as US certification."""
    merged: dict[str, dict] = {}
    for cache_name in ("tmdb-rich-details.json", "display-metadata.json"):
        cache_path = settings.processed_data_dir / cache_name
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for raw_tmdb_id, details in cached.items():
            if not str(raw_tmdb_id).lstrip("-").isdigit() or not isinstance(details, dict):
                continue
            merged.setdefault(str(raw_tmdb_id), {}).update(
                {key: value for key, value in details.items() if value is not None}
            )
    return merged


def _metadata_cache_version() -> tuple[tuple[str, int, int], ...]:
    version = []
    for cache_name in ("tmdb-rich-details.json", "display-metadata.json"):
        path = settings.processed_data_dir / cache_name
        try:
            stat = path.stat()
            version.append((cache_name, stat.st_mtime_ns, stat.st_size))
        except OSError:
            version.append((cache_name, 0, 0))
    return tuple(version)


@lru_cache(maxsize=4)
def _catalog_metadata_option_index(
    _version: tuple[tuple[str, int, int], ...],
) -> dict[str, dict[str, int]]:
    return build_metadata_filter_index(_load_profile_detail_cache())


def _local_movie_search_ids(query: str, year: int | None, limit: int) -> list[int]:
    """Search the bundled linked catalog when the live TMDB search is unavailable."""
    try:
        artifact = _latest_artifact(settings.ml_artifacts_dir)
        manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
        catalog_path = artifact / manifest["files"]["catalog"]
    except (RecommendationReportNotFound, FileNotFoundError, KeyError, json.JSONDecodeError):
        return []

    wanted = normalize_title(query)
    matches: list[tuple[int, int, int]] = []
    opener = gzip.open if catalog_path.suffix == ".gz" else open
    with opener(catalog_path, "rt", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            raw_tmdb_id = row.get("tmdb_id")
            if not raw_tmdb_id or not raw_tmdb_id.replace(".0", "", 1).isdigit():
                continue
            title = str(row.get("clean_title") or row.get("title") or "")
            normalized_title = normalize_title(title)
            if not wanted or wanted not in normalized_title:
                continue
            raw_year = str(row.get("year") or "")
            movie_year = int(float(raw_year)) if raw_year else None
            if year is not None and movie_year != year:
                continue
            if normalized_title == wanted:
                match_quality = 0
            elif normalized_title.startswith(wanted):
                match_quality = 1
            else:
                match_quality = 2
            matches.append((match_quality, -(movie_year or 0), int(float(raw_tmdb_id))))
    for cache_name in ("tmdb-rich-details.json", "display-metadata.json"):
        cache_path = settings.processed_data_dir / cache_name
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for raw_tmdb_id, details in cached.items():
            if details.get("missing") is True or not str(raw_tmdb_id).lstrip("-").isdigit():
                continue
            release = str(details.get("release_date") or "")
            movie_year = int(release[:4]) if release[:4].isdigit() else None
            if year is not None and movie_year != year:
                continue
            titles = {details.get("title"), details.get("original_title")}
            normalized_titles = {
                normalize_title(str(title)) for title in titles if str(title or "").strip()
            }
            matching_titles = [title for title in normalized_titles if wanted in title]
            if not matching_titles:
                continue
            best_quality = min(
                0 if title == wanted else 1 if title.startswith(wanted) else 2
                for title in matching_titles
            )
            matches.append((best_quality, -(movie_year or 0), int(raw_tmdb_id)))
    matches.sort()
    ordered = []
    for _, _, tmdb_id in matches:
        if tmdb_id not in ordered:
            ordered.append(tmdb_id)
        if len(ordered) >= limit:
            break
    return ordered


def _local_movie_search_results(query: str, year: int | None, limit: int) -> list[dict]:
    """Return display-ready matches from bundled catalog and metadata caches."""
    ordered_ids = _local_movie_search_ids(query, year, limit)
    if not ordered_ids:
        return []
    wanted_ids = set(ordered_ids)
    by_id: dict[int, dict] = {}
    for cache_name in ("tmdb-rich-details.json", "display-metadata.json"):
        cache_path = settings.processed_data_dir / cache_name
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for raw_tmdb_id, details in cached.items():
            if not str(raw_tmdb_id).lstrip("-").isdigit() or int(raw_tmdb_id) not in wanted_ids:
                continue
            tmdb_id = int(raw_tmdb_id)
            current = by_id.setdefault(tmdb_id, {})
            current.update({key: value for key, value in details.items() if value is not None})

    missing_ids = wanted_ids - set(by_id)
    if missing_ids:
        try:
            artifact = _latest_artifact(settings.ml_artifacts_dir)
            manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
            catalog_path = artifact / manifest["files"]["catalog"]
            opener = gzip.open if catalog_path.suffix == ".gz" else open
            with opener(catalog_path, "rt", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    raw_tmdb_id = str(row.get("tmdb_id") or "")
                    if not raw_tmdb_id.replace(".0", "", 1).isdigit():
                        continue
                    tmdb_id = int(float(raw_tmdb_id))
                    if tmdb_id not in missing_ids:
                        continue
                    raw_year = str(row.get("year") or "")
                    movie_year = int(float(raw_year)) if raw_year else None
                    by_id[tmdb_id] = {
                        "id": tmdb_id,
                        "title": row.get("clean_title") or row.get("title") or "Untitled",
                        "release_date": f"{movie_year}-01-01" if movie_year else None,
                    }
        except (RecommendationReportNotFound, FileNotFoundError, KeyError, json.JSONDecodeError):
            pass
    return [dict(by_id[tmdb_id], id=tmdb_id) for tmdb_id in ordered_ids if tmdb_id in by_id]


def _tmdb_search_ids(query: str, year: int | None, limit: int) -> list[int]:
    """Search TMDB, falling back to the bundled catalog after network retry failures."""
    local_ids = _local_movie_search_ids(query, year, limit)
    if not settings.tmdb_api_key:
        return local_ids
    client = TmdbClient(settings.tmdb_api_key)
    try:
        # Direct lookups should be able to find every TMDB movie. TMDB otherwise
        # silently omits adult-flagged records even for an exact title and year.
        movie_results = client.search_movie(query, year, include_adult=True)
        tv_results = [
            normalize_tv_search_result(item)
            for item in client.search_tv(query, year, include_adult=True)
            if item.get("id") is not None
        ]
        results = rank_title_search_results(query, [*movie_results, *tv_results], limit)
        ordered_ids = [int(item["id"]) for item in results if item.get("id") is not None]
        available, _ = load_or_fetch_details(
            client,
            set(ordered_ids),
            settings.processed_data_dir / "tmdb-rich-details.json",
        )
        live_ids = [tmdb_id for tmdb_id in ordered_ids if tmdb_id in available]
        return list(dict.fromkeys([*live_ids, *local_ids]))[:limit]
    except RetryError as error:
        if local_ids:
            return local_ids
        raise HTTPException(
            status_code=503,
            detail=(
                "TMDB is temporarily unreachable, and this title is not in the bundled "
                "offline catalog. Please retry the lookup when the connection is available."
            ),
        ) from error
    finally:
        client.close()


def _person_filter_candidate_ids(
    category: str | None,
    value: str | None,
    media_type: str,
) -> list[int] | None:
    """Expand actor/director filters beyond titles already present in the local cache."""
    if category not in {"actors", "directors"} or not value or not settings.tmdb_api_key:
        return None
    client = TmdbClient(settings.tmdb_api_key)
    try:
        people = client.search_person(value)
        wanted = normalize_title(value)
        exact = [person for person in people if normalize_title(person.get("name") or "") == wanted]
        candidates = exact or people
        if not candidates:
            return []
        person = max(candidates, key=lambda item: float(item.get("popularity") or 0.0))
        credits = client.person_combined_credits(int(person["id"]))
        rows = credits.get("cast", []) if category == "actors" else credits.get("crew", [])
        if category == "directors":
            rows = [row for row in rows if row.get("job") == "Director"]
        rows = [row for row in rows if not row.get("adult")]
        rows.sort(
            key=lambda row: (
                float(row.get("popularity") or 0.0),
                str(row.get("release_date") or row.get("first_air_date") or ""),
            ),
            reverse=True,
        )
        ids = []
        for row in rows:
            row_type = row.get("media_type") or ("tv" if row.get("name") else "movie")
            if media_type != "all" and row_type != media_type:
                continue
            tmdb_id = tv_catalog_id(int(row["id"])) if row_type == "tv" else int(row["id"])
            if tmdb_id not in ids:
                ids.append(tmdb_id)
        available, _ = load_or_fetch_details(
            client,
            set(ids[:250]),
            settings.processed_data_dir / "tmdb-rich-details.json",
        )
        return [tmdb_id for tmdb_id in ids if tmdb_id in available]
    except (RetryError, TmdbError):
        return None
    finally:
        client.close()


def _theme_filter_candidate_ids(value: str, media_type: str) -> list[int] | None:
    """Discover TMDB titles for a theme instead of limiting themes to the local cache."""
    if not value or not settings.tmdb_api_key:
        return None
    client = TmdbClient(settings.tmdb_api_key)
    try:
        keywords = client.search_keyword(value)
        wanted = normalize_title(value)
        exact = [item for item in keywords if normalize_title(item.get("name") or "") == wanted]
        selected = exact or keywords[:1]
        if not selected:
            return []
        media_types = [media_type] if media_type in {"movie", "tv"} else ["movie", "tv"]
        ids: list[int] = []
        for selected_type in media_types:
            for page in range(1, 6):
                response = client.discover_by_keyword(int(selected[0]["id"]), selected_type, page)
                for row in response.get("results", []):
                    raw_id = int(row["id"])
                    tmdb_id = tv_catalog_id(raw_id) if selected_type == "tv" else raw_id
                    if tmdb_id not in ids:
                        ids.append(tmdb_id)
                if page >= min(int(response.get("total_pages") or page), 5):
                    break
        available, _ = load_or_fetch_details(
            client,
            set(ids[:250]),
            settings.processed_data_dir / "tmdb-rich-details.json",
        )
        return [tmdb_id for tmdb_id in ids if tmdb_id in available]
    except (RetryError, TmdbError):
        return None
    finally:
        client.close()


def _company_filter_candidate_ids(value: str, media_type: str) -> list[int] | None:
    """Expand a production-company filter through TMDB's complete company catalog."""
    if not value or not settings.tmdb_api_key:
        return None
    client = TmdbClient(settings.tmdb_api_key)
    try:
        companies = client.search_company(value)
        wanted = normalize_title(value).replace(" ", "")
        related = [
            item
            for item in companies
            if wanted in normalize_title(item.get("name") or "").replace(" ", "")
            or normalize_title(item.get("name") or "").replace(" ", "") in wanted
        ][:5]
        selected = related or companies[:1]
        if not selected:
            return []
        media_types = [media_type] if media_type in {"movie", "tv"} else ["movie", "tv"]
        ids: list[int] = []
        for company in selected:
            for selected_type in media_types:
                for page in range(1, 6):
                    response = client.discover_by_company(int(company["id"]), selected_type, page)
                    for row in response.get("results", []):
                        raw_id = int(row["id"])
                        tmdb_id = tv_catalog_id(raw_id) if selected_type == "tv" else raw_id
                        if tmdb_id not in ids:
                            ids.append(tmdb_id)
                    if len(ids) >= 250 or page >= min(int(response.get("total_pages") or page), 5):
                        break
                if len(ids) >= 250:
                    break
            if len(ids) >= 250:
                break
        available, _ = load_or_fetch_details(
            client,
            set(ids[:250]),
            settings.processed_data_dir / "tmdb-rich-details.json",
        )
        return [tmdb_id for tmdb_id in ids if tmdb_id in available]
    except (RetryError, TmdbError):
        return None
    finally:
        client.close()


def _parse_metadata_filters(raw: str | None) -> list[dict[str, str]]:
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail="Invalid filter data") from error
    if not isinstance(values, list) or len(values) > 10:
        raise HTTPException(status_code=422, detail="Invalid filter data")
    return [
        {"category": str(item.get("category") or ""), "value": str(item.get("value") or "")}
        for item in values
        if isinstance(item, dict) and item.get("category") and item.get("value")
    ]


def _expanded_filter_candidate_ids(
    metadata_filters: list[dict[str, str]],
    title_filter: str | None,
    media_type: str,
) -> list[int] | None:
    expanded: list[list[int]] = []
    if title_filter:
        expanded.append(_tmdb_search_ids(title_filter, None, 25))
    for selected in metadata_filters:
        category = selected["category"]
        value = selected["value"]
        ids = (
            _person_filter_candidate_ids(category, value, media_type)
            if category in {"actors", "directors"}
            else _theme_filter_candidate_ids(value, media_type)
            if category == "themes"
            else _company_filter_candidate_ids(value, media_type)
            if category == "companies"
            else None
        )
        if ids is not None:
            expanded.append(ids)
    if not expanded:
        return None
    intersection = set(expanded[0])
    for values in expanded[1:]:
        intersection.intersection_update(values)
    return [value for value in expanded[0] if value in intersection]


def _cached_metadata_code(field: str, requested: str) -> str | None:
    """Resolve a human-readable cached language/country label to its TMDB code."""
    normalized = normalize_title(requested.replace("-language", ""))
    if field == "original_language":
        for code, label in LANGUAGE_NAMES.items():
            if normalize_title(label.replace("-language", "")) == normalized:
                return code
        if len(requested.strip()) in {2, 3}:
            return requested.strip().casefold()
        return None
    cache_path = settings.processed_data_dir / "tmdb-rich-details.json"
    if not cache_path.exists():
        return requested.strip().upper() if len(requested.strip()) == 2 else None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for details in cached.values():
        for country in details.get("production_countries") or []:
            if normalize_title(str(country.get("name") or "")) == normalized:
                return str(country.get("iso_3166_1") or "").upper() or None
    return requested.strip().upper() if len(requested.strip()) == 2 else None


def _best_named_result(values: list[dict], requested: str) -> dict | None:
    wanted = normalize_title(requested)
    exact = [item for item in values if normalize_title(item.get("name") or "") == wanted]
    candidates = exact or values
    return (
        max(candidates, key=lambda item: float(item.get("popularity") or 0.0))
        if candidates
        else None
    )


def _discover_filtered_candidate_ids(
    metadata_filters: list[dict[str, str]],
    title_filter: str | None,
    media_type: str,
    *,
    year_min: int | None = None,
    year_max: int | None = None,
    runtime_min: int | None = None,
    runtime_max: int | None = None,
    genre: str | None = None,
    certification: str | None = None,
    availability: str = "all",
    popularity: str = "all",
) -> tuple[list[int] | None, dict | None]:
    """Discover the complete TMDB-filtered pool, then cache lightweight scoring rows."""
    has_discovery_filter = any(
        value not in {None, "", "all"}
        for value in (
            year_min,
            year_max,
            runtime_min,
            runtime_max,
            genre,
            certification,
            availability,
            popularity,
        )
    ) or bool(metadata_filters)
    if not has_discovery_filter:
        ids = _tmdb_search_ids(title_filter, None, 100) if title_filter else None
        coverage = (
            {
                "mode": "tmdb_title_search",
                "matches_reported": len(ids or []),
                "matches_retrieved": len(ids or []),
                "pages_scanned": 1,
                "truncated": False,
            }
            if title_filter
            else None
        )
        return ids, coverage
    if not settings.tmdb_api_key:
        return _expanded_filter_candidate_ids(metadata_filters, title_filter, media_type), None
    if media_type == "all":
        movie_ids, movie_coverage = _discover_filtered_candidate_ids(
            metadata_filters,
            title_filter,
            "movie",
            year_min=year_min,
            year_max=year_max,
            runtime_min=runtime_min,
            runtime_max=runtime_max,
            genre=genre,
            certification=certification,
            availability=availability,
            popularity=popularity,
        )
        tv_ids, tv_coverage = _discover_filtered_candidate_ids(
            metadata_filters,
            title_filter,
            "tv",
            year_min=year_min,
            year_max=year_max,
            runtime_min=runtime_min,
            runtime_max=runtime_max,
            genre=genre,
            certification=certification,
            availability=availability,
            popularity=popularity,
        )
        ids = list(dict.fromkeys([*(movie_ids or []), *(tv_ids or [])]))
        coverages = [value for value in (movie_coverage, tv_coverage) if value]
        return ids, {
            "mode": "tmdb_discover",
            "matches_reported": sum(int(value.get("matches_reported") or 0) for value in coverages),
            "matches_retrieved": len(ids),
            "pages_scanned": sum(int(value.get("pages_scanned") or 0) for value in coverages),
            "page_cap": DISCOVERY_MAX_PAGES,
            "truncated": any(bool(value.get("truncated")) for value in coverages),
        }

    client = TmdbClient(settings.tmdb_api_key)
    try:
        params: dict[str, str | int] = {}
        if year_min:
            params["first_air_date.gte" if media_type == "tv" else "primary_release_date.gte"] = (
                f"{year_min}-01-01"
            )
        if year_max:
            params["first_air_date.lte" if media_type == "tv" else "primary_release_date.lte"] = (
                f"{year_max}-12-31"
            )
        if runtime_min:
            params["with_runtime.gte"] = runtime_min
        if runtime_max:
            params["with_runtime.lte"] = runtime_max
        if genre:
            aliases = (
                {
                    "Action": "Action & Adventure",
                    "Adventure": "Action & Adventure",
                    "Science Fiction": "Sci-Fi & Fantasy",
                    "Fantasy": "Sci-Fi & Fantasy",
                    "War": "War & Politics",
                }
                if media_type == "tv"
                else {
                    "Music": "Musical",
                    "Science Fiction": "Sci-Fi",
                    "Family": "Children",
                }
            )
            lookup = aliases.get(genre, genre).casefold()
            genre_map = TV_GENRES if media_type == "tv" else TMDB_GENRES
            genre_id = next(
                (key for key, value in genre_map.items() if value.casefold() == lookup), None
            )
            if genre_id is None:
                return [], {
                    "mode": "tmdb_discover",
                    "matches_reported": 0,
                    "matches_retrieved": 0,
                    "pages_scanned": 0,
                    "truncated": False,
                }
            params["with_genres"] = genre_id

        injected: dict[str, object] = {"_tmdb_discovery_prefiltered": True}
        person_filters: dict[str, list[str]] = {"actors": [], "directors": []}
        keyword_groups: list[str] = []
        company_groups: list[str] = []
        languages: list[str] = []
        countries: list[str] = []
        for selected in metadata_filters:
            category, value = selected["category"], selected["value"]
            if category in person_filters:
                person = _best_named_result(client.search_person(value), value)
                if person is None:
                    return [], {
                        "mode": "tmdb_discover",
                        "matches_reported": 0,
                        "matches_retrieved": 0,
                        "pages_scanned": 0,
                        "truncated": False,
                    }
                person_filters[category].append(str(int(person["id"])))
                credits = injected.setdefault("credits", {"cast": [], "crew": []})
                if category == "actors":
                    credits["cast"].append(
                        {"id": int(person["id"]), "name": person.get("name") or value}
                    )
                else:
                    credits["crew"].append(
                        {
                            "id": int(person["id"]),
                            "name": person.get("name") or value,
                            "job": "Director",
                        }
                    )
            elif category == "themes":
                keyword = _best_named_result(client.search_keyword(value), value)
                if keyword is None:
                    return [], {
                        "mode": "tmdb_discover",
                        "matches_reported": 0,
                        "matches_retrieved": 0,
                        "pages_scanned": 0,
                        "truncated": False,
                    }
                keyword_groups.append(str(int(keyword["id"])))
                injected.setdefault("keywords", {"keywords": []})["keywords"].append(
                    {"id": int(keyword["id"]), "name": keyword.get("name") or value}
                )
            elif category == "companies":
                companies = client.search_company(value)
                wanted = normalize_title(value).replace(" ", "")
                related = [
                    item
                    for item in companies
                    if wanted in normalize_title(item.get("name") or "").replace(" ", "")
                    or normalize_title(item.get("name") or "").replace(" ", "") in wanted
                ][:10]
                selected_companies = related or companies[:1]
                if not selected_companies:
                    return [], {
                        "mode": "tmdb_discover",
                        "matches_reported": 0,
                        "matches_retrieved": 0,
                        "pages_scanned": 0,
                        "truncated": False,
                    }
                company_groups.append("|".join(str(int(item["id"])) for item in selected_companies))
                injected.setdefault("production_companies", []).extend(
                    {"id": int(item["id"]), "name": item.get("name") or value}
                    for item in selected_companies
                )
            elif category == "languages":
                code = _cached_metadata_code("original_language", value)
                if code:
                    languages.append(code)
            elif category == "countries":
                code = _cached_metadata_code("production_countries", value)
                if code:
                    countries.append(code)
                    injected.setdefault("production_countries", []).append(
                        {"iso_3166_1": code, "name": value}
                    )
        if any(len(values) > 1 for values in (languages, countries)):
            return [], {
                "mode": "tmdb_discover",
                "matches_reported": 0,
                "matches_retrieved": 0,
                "pages_scanned": 0,
                "truncated": False,
            }
        if person_filters["actors"] and media_type == "movie":
            params["with_cast"] = ",".join(person_filters["actors"])
        elif person_filters["actors"]:
            params["with_people"] = ",".join(person_filters["actors"])
        if person_filters["directors"] and media_type == "movie":
            params["with_crew"] = ",".join(person_filters["directors"])
        elif person_filters["directors"]:
            params["with_people"] = ",".join(
                [*person_filters["actors"], *person_filters["directors"]]
            )
        if keyword_groups:
            params["with_keywords"] = ",".join(keyword_groups)
        if company_groups:
            params["with_companies"] = ",".join(company_groups)
        if languages:
            params["with_original_language"] = languages[0]
            injected["original_language"] = languages[0]
        if countries:
            params["with_origin_country"] = countries[0]
        if certification and certification != "all" and media_type == "movie":
            certification_map = {
                "g": "G",
                "pg": "PG",
                "pg-13": "PG-13",
                "r": "R",
                "nc-17": "NC-17",
            }
            if certification in certification_map:
                params.update(
                    {
                        "certification_country": "US",
                        "certification": certification_map[certification],
                    }
                )
        vote_ranges = {
            "blockbuster": (10_000, None),
            "popular": (2_500, None),
            "cult_classic": (250, None),
            "under_the_radar": (25, None),
            "unknown": (None, 24),
        }
        minimum_votes, maximum_votes = vote_ranges.get(popularity, (None, None))
        if minimum_votes is not None:
            params["vote_count.gte"] = minimum_votes
        if maximum_votes is not None:
            params["vote_count.lte"] = maximum_votes
            params["sort_by"] = "popularity.asc"
        availability_types = {
            "listed": "flatrate|free|ads|rent|buy",
            "subscription": "flatrate",
            "free": "free|ads",
            "rent_buy": "rent|buy",
        }
        if availability in availability_types:
            params.update(
                {
                    "watch_region": "US",
                    "with_watch_monetization_types": availability_types[availability],
                }
            )

        media_types = [media_type] if media_type in {"movie", "tv"} else ["movie", "tv"]
        all_rows: list[dict] = []
        total_reported = 0
        pages_scanned = 0
        truncated = False
        for selected_type in media_types:
            first = client.discover_filtered(selected_type, page=1, filters=params)
            total_reported += int(first.get("total_results") or 0)
            total_pages = int(first.get("total_pages") or 1)
            page_limit = min(total_pages, DISCOVERY_MAX_PAGES)
            truncated = truncated or total_pages > DISCOVERY_MAX_PAGES
            page_results = {1: first}
            if page_limit > 1:
                with ThreadPoolExecutor(max_workers=min(12, page_limit - 1)) as executor:
                    futures = {
                        executor.submit(
                            client.discover_filtered, selected_type, page=page, filters=params
                        ): page
                        for page in range(2, page_limit + 1)
                    }
                    for future in as_completed(futures):
                        page_results[futures[future]] = future.result()
            pages_scanned += page_limit
            genre_map = TV_GENRES if selected_type == "tv" else TMDB_GENRES
            for page in range(1, page_limit + 1):
                for raw in page_results[page].get("results", []):
                    row = normalize_tv_search_result(raw) if selected_type == "tv" else dict(raw)
                    row["media_type"] = selected_type
                    row["genres"] = [
                        {"id": genre_id, "name": genre_map[genre_id]}
                        for genre_id in row.get("genre_ids", [])
                        if genre_id in genre_map
                    ]
                    for key, value in injected.items():
                        row.setdefault(key, value)
                    all_rows.append(row)

        if title_filter:
            title_ids = set(_tmdb_search_ids(title_filter, None, 100))
            all_rows = [row for row in all_rows if int(row["id"]) in title_ids]
            total_reported = len(all_rows)
        unique_rows = {int(row["id"]): row for row in all_rows}
        merge_discovery_results(
            settings.processed_data_dir / "tmdb-rich-details.json",
            list(unique_rows.values()),
        )
        coverage = {
            "mode": "tmdb_discover",
            "matches_reported": total_reported,
            "matches_retrieved": len(unique_rows),
            "pages_scanned": pages_scanned,
            "page_cap": DISCOVERY_MAX_PAGES,
            "truncated": truncated,
        }
        return list(unique_rows), coverage
    except (RetryError, TmdbError):
        return _expanded_filter_candidate_ids(metadata_filters, title_filter, media_type), {
            "mode": "offline_catalog_fallback",
            "matches_reported": None,
            "matches_retrieved": None,
            "pages_scanned": 0,
            "truncated": True,
        }
    finally:
        client.close()


def _candidate_ids_argument(values: list[int] | None) -> str | None:
    if values is None:
        return None
    return ",".join(str(value) for value in values) or "-999999999"


@app.middleware("http")
async def disable_local_ui_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.app_env,
        "tmdb": "configured" if settings.tmdb_api_key else "missing",
    }


@app.get("/tmdb/status")
def tmdb_status() -> dict:
    """Actively verify TMDB while advertising the bundled-catalog fallback."""
    if not settings.tmdb_api_key:
        return {
            "configured": False,
            "live": False,
            "fallback_available": True,
            "message": "TMDB key missing; bundled catalog is available.",
        }
    client = TmdbClient(settings.tmdb_api_key)
    try:
        client.check_connection()
        return {
            "configured": True,
            "live": True,
            "fallback_available": True,
            "message": "TMDB live connection is working.",
        }
    except RetryError:
        return {
            "configured": True,
            "live": False,
            "fallback_available": True,
            "message": "TMDB network is temporarily unavailable; bundled catalog is active.",
        }
    except TmdbError as error:
        return {
            "configured": True,
            "live": False,
            "fallback_available": True,
            "message": str(error),
        }
    finally:
        client.close()


@app.get("/catalog/status")
def catalog_status() -> dict:
    summary = load_catalog_summary(settings.processed_data_dir / "tmdb-catalog-manifest.json")
    return {
        "synced": summary is not None,
        "tmdb_daily_export": summary,
    }


@app.get("/catalog/metadata-options")
def catalog_metadata_options(
    category: str = Query(max_length=30),
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=12, ge=1, le=30),
) -> dict:
    """Return exact catalog traits for dropdowns and type-ahead filters."""
    try:
        return metadata_filter_options(
            {},
            category,
            query=q,
            limit=limit,
            option_index=_catalog_metadata_option_index(_metadata_cache_version()),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/profiles")
def profiles() -> dict:
    """List locally imported profiles for persistent frontend selectors."""
    artifact = _latest_artifact(settings.ml_artifacts_dir)
    with SessionLocal() as session:
        owners = session.scalars(select(User).order_by(User.created_at, User.slug)).all()
        result = []
        for owner in owners:
            ranking_ready = (artifact / "recommendations" / owner.slug / "all.json").exists()
            total = (
                session.scalar(
                    select(func.count())
                    .select_from(ImportMapping)
                    .where(ImportMapping.user_id == owner.id)
                )
                or 0
            )
            if not total:
                continue
            mapped = (
                session.scalar(
                    select(func.count())
                    .select_from(ImportMapping)
                    .where(
                        ImportMapping.user_id == owner.id,
                        ImportMapping.status.in_(("matched", "matched_local", "matched_manual")),
                    )
                )
                or 0
            )
            rated = (
                session.scalar(
                    select(func.count())
                    .select_from(ImportMapping)
                    .where(
                        ImportMapping.user_id == owner.id,
                        ImportMapping.rating.is_not(None),
                    )
                )
                or 0
            )
            result.append(
                {
                    "slug": owner.slug,
                    "display_name": owner.display_name,
                    "films": total,
                    "rated": rated,
                    "mapped": mapped,
                    "pending": total - mapped,
                    "ranking_ready": ranking_ready,
                }
            )
    deduplicated: dict[str, dict] = {}
    for profile in result:
        key = profile["slug"].casefold()
        existing = deduplicated.get(key)
        if (
            existing is None
            or profile["mapped"] > existing["mapped"]
            or profile["mapped"] == existing["mapped"]
            and profile["ranking_ready"]
            and not existing["ranking_ready"]
        ):
            deduplicated[key] = profile
    return {"profiles": list(deduplicated.values())}


@app.patch("/profiles/{user}")
def update_profile(user: str, request: ProfileUpdateRequest) -> dict:
    """Update user-facing profile details without changing its stable internal ID."""
    from app.services.recommendation_reports import VALID_USER

    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    display_name = request.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="Display name cannot be empty")
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.slug == user))
        if owner is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        owner.display_name = display_name
        session.commit()
    return {"slug": user, "display_name": display_name}


@app.get("/profiles/{user}/stats")
def profile_stats(
    user: str,
    watched_year_min: int | None = Query(default=None, ge=1870, le=2200),
    watched_year_max: int | None = Query(default=None, ge=1870, le=2200),
) -> dict:
    """Return rating-only statistics for one imported profile."""
    from app.services.recommendation_reports import VALID_USER

    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    if (
        watched_year_min is not None
        and watched_year_max is not None
        and watched_year_min > watched_year_max
    ):
        raise HTTPException(status_code=422, detail="From year must not exceed through year")
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.slug == user))
        if owner is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        rows = session.execute(
            select(
                Movie.title,
                UserMovieInteraction.rating,
                UserMovieInteraction.review_text,
                UserMovieInteraction.rewatch_count,
                Movie.year,
                UserMovieInteraction.watched_date,
                Movie.tmdb_id,
                Movie.runtime,
            )
            .join(Movie, Movie.id == UserMovieInteraction.movie_id)
            .where(
                UserMovieInteraction.user_id == owner.id,
                UserMovieInteraction.rating.is_not(None),
            )
        ).all()
        last_import = session.scalar(
            select(func.max(ImportRun.completed_at)).where(ImportRun.user_id == owner.id)
        )
    all_rows = rows
    if watched_year_min is not None or watched_year_max is not None:
        rows = [
            row
            for row in all_rows
            if row.watched_date is not None
            and (watched_year_min is None or row.watched_date.year >= watched_year_min)
            and (watched_year_max is None or row.watched_date.year <= watched_year_max)
        ]
    ratings = [float(row.rating) for row in rows]
    distribution = {f"{value / 2:.1f}": 0 for value in range(1, 11)}
    for rating in ratings:
        distribution[f"{rating:.1f}"] = distribution.get(f"{rating:.1f}", 0) + 1
    details_raw = _load_profile_detail_cache()
    details_by_id = {
        int(key): value for key, value in details_raw.items() if str(key).lstrip("-").isdigit()
    }
    rated_movies = [
        {
            "title": row.title,
            "rating": float(row.rating),
            "year": row.year,
            "tmdb_id": row.tmdb_id,
            "runtime": row.runtime,
        }
        for row in rows
    ]
    taste_breakdown = build_taste_breakdown(
        rated_movies,
        details_by_id,
    )
    return {
        "slug": owner.slug,
        "display_name": owner.display_name,
        "rated_films": len(ratings),
        "mapped_films": len(rows),
        "pending_films": 0,
        "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "median_rating": round(float(median(ratings)), 2) if ratings else None,
        "lowest_rating": min(ratings) if ratings else None,
        "highest_rating": max(ratings) if ratings else None,
        "rated_reviews": sum(bool((row.review_text or "").strip()) for row in rows),
        "rewatches": sum(int(row.rewatch_count or 0) for row in rows),
        "rewatched_titles": [
            {"title": row.title, "count": int(row.rewatch_count or 0)}
            for row in rows
            if int(row.rewatch_count or 0) > 0
        ],
        "rating_distribution": distribution,
        "taste_breakdown": taste_breakdown,
        "public_opinion_splits": build_public_opinion_splits(
            rated_movies,
            details_by_id,
        ),
        "watched_year_filter": {
            "minimum": watched_year_min,
            "maximum": watched_year_max,
        },
        "available_watched_years": {
            "minimum": min(
                (row.watched_date.year for row in all_rows if row.watched_date), default=None
            ),
            "maximum": max(
                (row.watched_date.year for row in all_rows if row.watched_date), default=None
            ),
        },
        "available_review_years": sorted(
            {
                row.watched_date.year
                for row in all_rows
                if row.watched_date and str(row.review_text or "").strip()
            },
            reverse=True,
        ),
        "undated_ratings_excluded": (
            sum(row.watched_date is None for row in all_rows)
            if watched_year_min is not None or watched_year_max is not None
            else 0
        ),
        "last_imported_at": last_import.isoformat() if last_import else None,
    }


@app.get("/profiles/{user}/stats/movies")
def profile_stat_movies(
    user: str,
    category: str = Query(max_length=30),
    value: str = Query(min_length=1, max_length=200),
    watched_year: int | None = Query(default=None, ge=1870, le=2200),
) -> dict:
    """List the unique rated films contributing to one taste-stat row."""
    from app.services.recommendation_reports import VALID_USER

    valid_categories = {
        "genres",
        "themes",
        "decades",
        "directors",
        "actors",
        "languages",
        "countries",
        "companies",
        "runtimes",
        "popularity",
        "certifications",
    }
    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    if category not in valid_categories:
        raise HTTPException(status_code=422, detail="Invalid statistics category")
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.slug == user))
        if owner is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        rows = session.execute(
            select(Movie, UserMovieInteraction)
            .join(UserMovieInteraction, UserMovieInteraction.movie_id == Movie.id)
            .where(
                UserMovieInteraction.user_id == owner.id,
                UserMovieInteraction.rating.is_not(None),
            )
            .order_by(
                UserMovieInteraction.watched_date.desc(),
                UserMovieInteraction.rating.desc(),
                Movie.title,
            )
        ).all()
    details_raw = _load_profile_detail_cache()
    matches = []
    for movie, interaction in rows:
        if watched_year is not None and (
            interaction.watched_date is None or interaction.watched_date.year != watched_year
        ):
            continue
        details = details_raw.get(str(movie.tmdb_id), {}) if movie.tmdb_id else {}
        labels = movie_category_labels({"year": movie.year, "runtime": movie.runtime}, details).get(
            category, ()
        )
        if value not in labels:
            continue
        poster_path = movie.poster_path or details.get("poster_path")
        matches.append(
            {
                "tmdb_id": movie.tmdb_id,
                "title": movie.title,
                "year": movie.year,
                "rating": float(interaction.rating),
                "watched_date": (
                    interaction.watched_date.isoformat() if interaction.watched_date else None
                ),
                "review_text": interaction.review_text,
                "poster_url": (
                    f"https://image.tmdb.org/t/p/w185{poster_path}" if poster_path else None
                ),
            }
        )
    return {
        "user": user,
        "display_name": owner.display_name,
        "category": category,
        "value": value,
        "watched_year": watched_year,
        "count": len(matches),
        "movies": matches,
    }


@app.get("/profiles/{user}/stats/category")
def profile_stat_category(
    user: str,
    category: str = Query(max_length=30),
    watched_year: int | None = Query(default=None, ge=1870, le=2200),
) -> dict:
    """Return the strongest and weakest values within one taste category."""
    from app.services.recommendation_reports import VALID_USER

    valid_categories = {
        "genres",
        "themes",
        "decades",
        "directors",
        "actors",
        "languages",
        "countries",
        "companies",
        "runtimes",
        "popularity",
        "certifications",
    }
    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    if category not in valid_categories:
        raise HTTPException(status_code=422, detail="Invalid statistics category")
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.slug == user))
        if owner is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        display_name = owner.display_name
        rows = session.execute(
            select(Movie, UserMovieInteraction)
            .join(UserMovieInteraction, UserMovieInteraction.movie_id == Movie.id)
            .where(
                UserMovieInteraction.user_id == owner.id,
                UserMovieInteraction.rating.is_not(None),
            )
        ).all()
    if watched_year is not None:
        rows = [
            (movie, interaction)
            for movie, interaction in rows
            if interaction.watched_date is not None
            and interaction.watched_date.year == watched_year
        ]
    details_raw = _load_profile_detail_cache()
    details_by_id = {int(key): value for key, value in details_raw.items() if str(key).isdigit()}
    breakdown = build_taste_breakdown(
        [
            {
                "rating": float(interaction.rating),
                "year": movie.year,
                "tmdb_id": movie.tmdb_id,
                "runtime": movie.runtime,
            }
            for movie, interaction in rows
        ],
        details_by_id,
        limit=None,
        include_singletons=True,
    )
    ranked = breakdown.get(category, [])
    top_count = min(25, (len(ranked) + 1) // 2) if len(ranked) <= 50 else 25
    bottom_count = min(25, len(ranked) - top_count) if len(ranked) <= 50 else 25
    return {
        "user": user,
        "display_name": display_name,
        "category": category,
        "watched_year": watched_year,
        "count": len(ranked),
        "top": ranked[:top_count],
        "bottom": list(reversed(ranked[-bottom_count:])) if bottom_count else [],
    }


@app.get("/profiles/{user}/stats/descriptor")
def profile_descriptor_stat(
    user: str,
    match: str = Query(min_length=3, max_length=250),
) -> dict:
    """Explain one recommendation descriptor using this profile's rated films."""
    from app.services.recommendation_reports import VALID_USER

    target = metadata_match_stat_target(match)
    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    if target is None:
        raise HTTPException(status_code=422, detail="This descriptor has no profile statistic")
    category, requested_value = target
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.slug == user))
        if owner is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        rows = session.execute(
            select(Movie, UserMovieInteraction)
            .join(UserMovieInteraction, UserMovieInteraction.movie_id == Movie.id)
            .where(
                UserMovieInteraction.user_id == owner.id,
                UserMovieInteraction.rating.is_not(None),
            )
            .order_by(
                UserMovieInteraction.watched_date.desc(),
                UserMovieInteraction.rating.desc(),
                Movie.title,
            )
        ).all()
    details_raw = _load_profile_detail_cache()
    ratings = [float(interaction.rating) for _, interaction in rows]
    profile_average = sum(ratings) / len(ratings) if ratings else 0.0
    movies = []
    resolved_value = requested_value
    for movie, interaction in rows:
        details = details_raw.get(str(movie.tmdb_id), {}) if movie.tmdb_id else {}
        labels = movie_category_labels({"year": movie.year, "runtime": movie.runtime}, details).get(
            category, ()
        )
        actual_label = next(
            (label for label in labels if category_label_matches(label, requested_value)), None
        )
        if actual_label is None:
            continue
        resolved_value = actual_label
        poster_path = movie.poster_path or details.get("poster_path")
        movies.append(
            {
                "tmdb_id": movie.tmdb_id,
                "title": movie.title,
                "year": movie.year,
                "rating": float(interaction.rating),
                "watched_date": (
                    interaction.watched_date.isoformat() if interaction.watched_date else None
                ),
                "review_text": interaction.review_text,
                "poster_url": (
                    f"https://image.tmdb.org/t/p/w185{poster_path}" if poster_path else None
                ),
            }
        )
    matching_ratings = [movie["rating"] for movie in movies]
    observed_average = sum(matching_ratings) / len(matching_ratings) if matching_ratings else None
    expected_rating = (
        (sum(matching_ratings) + 3 * profile_average) / (len(matching_ratings) + 3)
        if matching_ratings
        else None
    )
    return {
        "user": user,
        "display_name": owner.display_name,
        "category": category,
        "value": resolved_value,
        "count": len(movies),
        "observed_average": round(observed_average, 2) if observed_average is not None else None,
        "expected_rating": round(expected_rating, 2) if expected_rating is not None else None,
        "profile_average": round(profile_average, 2) if ratings else None,
        "movies": movies,
    }


@app.get("/profiles/{user}/stats/people")
def profile_seen_people(user: str) -> dict:
    """Return directors and cast members represented in a profile's rated history."""
    from app.services.recommendation_reports import VALID_USER

    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.slug == user))
        if owner is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        movies = session.scalars(
            select(Movie)
            .join(UserMovieInteraction, UserMovieInteraction.movie_id == Movie.id)
            .where(
                UserMovieInteraction.user_id == owner.id,
                UserMovieInteraction.rating.is_not(None),
            )
        ).all()
        display_name = owner.display_name
    details_raw = _load_profile_detail_cache()
    directors: set[str] = set()
    actors: set[str] = set()
    for movie in movies:
        details = details_raw.get(str(movie.tmdb_id), {}) if movie.tmdb_id else {}
        labels = movie_category_labels({"year": movie.year, "runtime": movie.runtime}, details)
        directors.update(labels["directors"])
        actors.update(labels["actors"])
    return {
        "user": user,
        "display_name": display_name,
        "directors": sorted(directors),
        "actors": sorted(actors),
    }


@app.get("/profiles/{user}/ratings")
def profile_rating_history(user: str) -> dict:
    """Return a profile's rated movies, newest watches first and high ratings first."""
    from app.services.recommendation_reports import VALID_USER

    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.slug == user))
        if owner is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        rows = session.execute(
            select(Movie, UserMovieInteraction)
            .join(UserMovieInteraction, UserMovieInteraction.movie_id == Movie.id)
            .where(
                UserMovieInteraction.user_id == owner.id,
                UserMovieInteraction.rating.is_not(None),
            )
            .order_by(
                UserMovieInteraction.watched_date.desc(),
                UserMovieInteraction.imported_at.desc(),
                UserMovieInteraction.rating.desc(),
                Movie.title,
            )
        ).all()
    metadata_caches = []
    for cache_name in ("display-metadata.json", "tmdb-rich-details.json"):
        cache_path = settings.processed_data_dir / cache_name
        try:
            metadata_caches.append(
                json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
            )
        except (OSError, json.JSONDecodeError):
            metadata_caches.append({})
    ratings = []
    for movie, interaction in rows:
        metadata = next(
            (
                cache[str(movie.tmdb_id)]
                for cache in metadata_caches
                if movie.tmdb_id and str(movie.tmdb_id) in cache
            ),
            {},
        )
        poster_path = movie.poster_path or metadata.get("poster_path")
        ratings.append(
            {
                "movie_id": movie.id,
                "tmdb_id": movie.tmdb_id,
                "title": movie.title,
                "year": movie.year,
                "rating": float(interaction.rating),
                "watched_date": (
                    interaction.watched_date.isoformat() if interaction.watched_date else None
                ),
                "review_text": interaction.review_text,
                "rewatch_count": int(interaction.rewatch_count or 0),
                "poster_url": (
                    f"https://image.tmdb.org/t/p/w185{poster_path}" if poster_path else None
                ),
            }
        )
    return {
        "user": user,
        "display_name": owner.display_name,
        "count": len(ratings),
        "sort": "watched_date_desc_then_rating_desc",
        "ratings": ratings,
    }


@app.get("/profiles/{user}/export")
def export_profile(user: str) -> StreamingResponse:
    """Download a rating-only profile backup accepted by the existing import flow."""
    from app.services.recommendation_reports import VALID_USER

    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    try:
        with SessionLocal() as session:
            content, filename, _ = build_profile_archive(
                session,
                user,
                settings.processed_data_dir / "tmdb-rich-details.json",
            )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/profiles/{user}/accuracy")
def profile_accuracy(user: str) -> dict:
    """Measure personal prediction accuracy using repeated held-out ratings."""
    from app.services.recommendation_reports import VALID_USER

    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    try:
        result = evaluate_profile_accuracy(_latest_artifact(settings.ml_artifacts_dir), user)
        result["review_signal_policy"] = load_review_policy(
            settings.processed_data_dir / "review-policies" / f"{user}.json"
        )
        return result
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/movies/rating-search")
def rating_movie_search(
    q: str = Query(min_length=2, max_length=120),
    year: int | None = Query(default=None, ge=1870, le=2200),
    user: str | None = Query(default=None, max_length=100),
) -> dict:
    """Find exact TMDB records before adding a manual profile rating."""
    if not settings.tmdb_api_key:
        results = _local_movie_search_results(q, year, 12)
        if not results:
            raise HTTPException(status_code=503, detail="TMDB_API_KEY is not configured")
        search_warning = "TMDB is unavailable; showing matches from the bundled catalog."
    else:
        client = TmdbClient(settings.tmdb_api_key)
        local_results = _local_movie_search_results(q, year, 12)
        try:
            live_movies = client.search_movie(q, year, include_adult=True)
            live_tv = [
                normalize_tv_search_result(item)
                for item in client.search_tv(q, year, include_adult=True)
                if item.get("id") is not None
            ]
            live_results = [*live_movies, *live_tv]
            results_by_id = {
                int(item["id"]): item for item in [*local_results, *live_results] if item.get("id")
            }
            ranked_results = rank_title_search_results(q, [*live_results, *local_results], 12)
            ordered_ids = [int(item["id"]) for item in ranked_results if item.get("id")]
            results = [results_by_id[item_id] for item_id in dict.fromkeys(ordered_ids)][:12]
            search_warning = None
        except RetryError as error:
            if not local_results:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "TMDB is temporarily unreachable, and this title is not in the bundled "
                        "offline catalog. Please retry when the connection is available."
                    ),
                ) from error
            results = local_results
            search_warning = "TMDB is temporarily unreachable; showing bundled catalog matches."
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail=f"Movie search could not reach TMDB: {type(error).__name__}",
            ) from error
        finally:
            client.close()
    result_rows = [
        {
            "tmdb_id": int(item["id"]),
            "title": item.get("title") or item.get("original_title") or "Untitled",
            "year": (
                int(str(item.get("release_date"))[:4])
                if str(item.get("release_date") or "")[:4].isdigit()
                else None
            ),
            "poster_url": (
                f"https://image.tmdb.org/t/p/w185{item['poster_path']}"
                if item.get("poster_path")
                else None
            ),
            "media_type": item.get("media_type") or "movie",
            "adult": bool(item.get("adult", False)),
        }
        for item in results
        if item.get("id") is not None
    ]
    if user:
        from app.services.recommendation_reports import VALID_USER

        if not VALID_USER.fullmatch(user):
            raise HTTPException(status_code=422, detail="Invalid profile ID")
        result_ids = [item["tmdb_id"] for item in result_rows]
        with SessionLocal() as session:
            existing = session.execute(
                select(Movie.tmdb_id, UserMovieInteraction)
                .join(UserMovieInteraction, UserMovieInteraction.movie_id == Movie.id)
                .join(User, User.id == UserMovieInteraction.user_id)
                .where(User.slug == user, Movie.tmdb_id.in_(result_ids))
            ).all()
        by_tmdb = {int(tmdb_id): interaction for tmdb_id, interaction in existing}
        for item in result_rows:
            interaction = by_tmdb.get(item["tmdb_id"])
            item["current_rating"] = (
                float(interaction.rating) if interaction and interaction.rating else None
            )
            item["current_review_text"] = interaction.review_text if interaction else None
    return {"results": result_rows, "warning": search_warning}


@app.delete("/profiles/{user}/ratings/{movie_id}")
def delete_profile_rating(user: str, movie_id: int) -> dict:
    """Remove one mistaken rating and rebuild the profile without that movie."""
    from app.services.recommendation_reports import VALID_USER

    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.slug == user))
        if owner is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        row = session.execute(
            select(Movie, UserMovieInteraction)
            .join(UserMovieInteraction, UserMovieInteraction.movie_id == Movie.id)
            .where(
                UserMovieInteraction.user_id == owner.id,
                UserMovieInteraction.movie_id == movie_id,
                UserMovieInteraction.rating.is_not(None),
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Rated movie not found")
        movie, interaction = row
        title = movie.title
        mappings = session.scalars(
            select(ImportMapping).where(
                ImportMapping.user_id == owner.id,
                ImportMapping.movie_id == movie.id,
            )
        ).all()
        for mapping in mappings:
            session.delete(mapping)
        session.delete(interaction)
        session.commit()

    review_policy_warning = None
    try:
        refresh_review_policy(
            user,
            settings.processed_data_dir / "tmdb-rich-details.json",
            settings.processed_data_dir / "review-policies" / f"{user}.json",
        )
    except Exception as error:
        review_policy_warning = f"Review policy refresh failed: {type(error).__name__}"
    clear_group_recommendation_cache()
    ranking_warning = None
    try:
        generate_recommendations(
            _latest_artifact(settings.ml_artifacts_dir),
            user=user,
            limit=20,
            scope="all",
            live_tmdb=False,
            persist=True,
            emit=False,
        )
    except Exception as error:
        ranking_warning = f"Rating removed, but ranking refresh failed: {type(error).__name__}"
    return {
        "user": user,
        "movie_id": movie_id,
        "title": title,
        "deleted": True,
        "ranking_updated": ranking_warning is None,
        "ranking_warning": ranking_warning,
        "review_policy_warning": review_policy_warning,
    }


@app.put("/profiles/{user}/ratings")
def save_manual_rating(user: str, request: ManualRatingRequest) -> dict:
    """Add or update one rated film and immediately refresh the personal model."""
    from app.services.recommendation_reports import VALID_USER

    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    if request.tmdb_id == 0:
        raise HTTPException(status_code=422, detail="Invalid TMDB title ID")
    details_cache_path = settings.processed_data_dir / "tmdb-rich-details.json"
    try:
        cached_details = (
            json.loads(details_cache_path.read_text(encoding="utf-8"))
            if details_cache_path.is_file()
            else {}
        )
    except (OSError, json.JSONDecodeError):
        cached_details = {}
    cached_movie = cached_details.get(str(request.tmdb_id))
    details_warning = None
    details = None
    if settings.tmdb_api_key:
        client = TmdbClient(settings.tmdb_api_key)
        try:
            if is_tv_catalog_id(request.tmdb_id):
                details = normalize_tv_details(
                    client.tv_details(
                        abs(request.tmdb_id),
                        "keywords,credits,content_ratings",
                    )
                )
            else:
                details = client.movie_details(
                    request.tmdb_id,
                    "keywords,credits,release_dates",
                )
        except RetryError as error:
            if cached_movie and cached_movie.get("missing") is not True:
                details = cached_movie
                details_warning = (
                    "TMDB was temporarily unreachable; verified bundled movie details were used."
                )
            else:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "TMDB is temporarily unreachable and this movie is not yet cached. "
                        "Your rating was not changed; please retry shortly."
                    ),
                ) from error
        except Exception as error:
            raise HTTPException(
                status_code=422, detail="TMDB rejected the selected movie details"
            ) from error
        finally:
            client.close()
    elif cached_movie and cached_movie.get("missing") is not True:
        details = cached_movie
        details_warning = "Verified bundled movie details were used."
    else:
        raise HTTPException(
            status_code=503,
            detail="TMDB is unavailable and this selected movie is not in the bundled cache.",
        )
    assert details is not None
    cached_details[str(request.tmdb_id)] = details
    details_cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_cache = details_cache_path.with_suffix(".tmp")
    temporary_cache.write_text(json.dumps(cached_details), encoding="utf-8")
    temporary_cache.replace(details_cache_path)
    release = str(details.get("release_date") or "")
    try:
        release_date = date.fromisoformat(release) if release else None
    except ValueError:
        release_date = None
    title = str(details.get("title") or request.title)
    year = int(release[:4]) if release[:4].isdigit() else request.year
    review = (request.review_text or "").strip() or None
    entered_on = date.today()
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.slug == user))
        if owner is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        movie = session.scalar(select(Movie).where(Movie.tmdb_id == request.tmdb_id))
        if movie is None:
            movie = Movie(tmdb_id=request.tmdb_id, title=title, original_title=title, year=year)
            session.add(movie)
            session.flush()
        movie.title = title
        movie.original_title = details.get("original_title") or title
        movie.year = year
        movie.release_date = release_date
        movie.overview = details.get("overview")
        movie.runtime = details.get("runtime")
        movie.poster_path = details.get("poster_path")
        interaction = session.scalar(
            select(UserMovieInteraction).where(
                UserMovieInteraction.user_id == owner.id,
                UserMovieInteraction.movie_id == movie.id,
            )
        )
        if interaction is None:
            interaction = UserMovieInteraction(
                user_id=owner.id,
                movie_id=movie.id,
                source="manual",
            )
            session.add(interaction)
        interaction.rating = Decimal(str(request.rating))
        interaction.review_text = review
        interaction.watched = True
        interaction.watched_date = entered_on
        mapping = session.scalar(
            select(ImportMapping).where(
                ImportMapping.user_id == owner.id,
                ImportMapping.movie_id == movie.id,
            )
        )
        if mapping is None:
            mapping = ImportMapping(
                user_id=owner.id,
                source="manual",
                source_key=(
                    f"tmdb:tv:{abs(request.tmdb_id)}"
                    if is_tv_catalog_id(request.tmdb_id)
                    else f"tmdb:movie:{request.tmdb_id}"
                ),
                movie_id=movie.id,
                title=title,
                year=year,
                status="matched_manual",
                watched=True,
            )
            session.add(mapping)
        mapping.rating = Decimal(str(request.rating))
        mapping.review_text = review
        mapping.watched = True
        mapping.watched_date = entered_on
        mapping.title = title
        mapping.year = year
        mapping.status = "matched_manual" if mapping.source == "manual" else mapping.status
        session.commit()
    review_policy = refresh_review_policy(
        user,
        settings.processed_data_dir / "tmdb-rich-details.json",
        settings.processed_data_dir / "review-policies" / f"{user}.json",
    )
    clear_group_recommendation_cache()
    ranking_warning = None
    try:
        generate_recommendations(
            _latest_artifact(settings.ml_artifacts_dir),
            user=user,
            limit=20,
            scope="all",
            live_tmdb=False,
            persist=True,
            emit=False,
        )
    except Exception as error:
        ranking_warning = f"Rating saved, but ranking refresh failed: {type(error).__name__}"
    return {
        "user": user,
        "tmdb_id": request.tmdb_id,
        "media_type": "tv" if is_tv_catalog_id(request.tmdb_id) else "movie",
        "title": title,
        "rating": request.rating,
        "review_saved": review is not None,
        "ranking_updated": ranking_warning is None,
        "ranking_warning": ranking_warning,
        "details_warning": details_warning,
        "review_signal_policy": review_policy,
    }


def _delete_profile_files(user: str) -> list[str]:
    warnings = []
    artifact_root = settings.ml_artifacts_dir.resolve()
    for candidate in artifact_root.glob(f"*/recommendations/{user}"):
        resolved = candidate.resolve()
        if not resolved.is_relative_to(artifact_root) or not resolved.is_dir():
            continue
        try:
            rmtree(resolved)
        except OSError:
            warnings.append(f"Could not remove generated ranking directory: {resolved.name}")
    policy = (settings.processed_data_dir / "review-policies" / f"{user}.json").resolve()
    processed_root = settings.processed_data_dir.resolve()
    if policy.is_relative_to(processed_root) and policy.is_file():
        try:
            policy.unlink()
        except OSError:
            warnings.append("Could not remove the generated review-policy file")
    return warnings


@app.delete("/profiles/{user}")
def delete_profile(user: str, request: ProfileDeleteRequest) -> dict:
    """Delete one profile and its imported interactions after exact typed confirmation."""
    from app.services.recommendation_reports import VALID_USER

    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.slug == user))
        if owner is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        if request.confirmation not in {owner.slug, owner.display_name}:
            raise HTTPException(
                status_code=422,
                detail=f"Type {owner.display_name} or {owner.slug} exactly to confirm deletion",
            )
        if (session.scalar(select(func.count()).select_from(User)) or 0) <= 1:
            raise HTTPException(status_code=409, detail="The last profile cannot be deleted")
        session.delete(owner)
        session.commit()
    warnings = _delete_profile_files(user)
    clear_group_recommendation_cache()
    return {"deleted": user, "warnings": warnings}


@app.post("/groups/recommendations")
def group_recommendations(request: GroupRecommendationRequest) -> dict:
    try:
        metadata_filters = [item.model_dump() for item in request.metadata_filters]
        if request.metadata_category and request.metadata_value:
            metadata_filters.append(
                {"category": request.metadata_category, "value": request.metadata_value}
            )
        expanded_candidate_ids, discovery_coverage = _discover_filtered_candidate_ids(
            metadata_filters,
            request.title_filter,
            request.media_type,
            year_min=request.year_min,
            year_max=request.year_max,
            runtime_min=request.runtime_min,
            runtime_max=request.runtime_max,
            genre=request.genre,
            certification=request.certification,
            availability=request.availability,
            popularity=request.popularity,
        )
        report = generate_group_recommendations(
            _latest_artifact(settings.ml_artifacts_dir),
            request.users,
            limit=request.limit,
            year_min=request.year_min,
            year_max=request.year_max,
            runtime_min=request.runtime_min,
            runtime_max=request.runtime_max,
            popularity=request.popularity,
            genre=request.genre,
            metadata_category=request.metadata_category,
            metadata_value=request.metadata_value,
            metadata_filters=json.dumps(metadata_filters) if metadata_filters else None,
            media_type=request.media_type,
            candidate_tmdb_ids=_candidate_ids_argument(expanded_candidate_ids),
            include_watched=request.include_watched,
            exclude_any_watched=request.exclude_any_watched,
        )
        if discovery_coverage:
            discovery_coverage["candidates_scored"] = int(report.get("eligible_for_everyone") or 0)
            report["discovery_coverage"] = discovery_coverage
        return _with_display_metadata(report, request.country)
    except (ValueError, typer.BadParameter) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Group ranking could not be completed: {type(error).__name__}",
        ) from error


@app.post("/groups/search")
def group_movie_search(request: GroupMovieSearchRequest) -> dict:
    """Search TMDB and score exact matches for every profile in a movie-night group."""
    try:
        tmdb_ids = _tmdb_search_ids(request.query, request.year, request.limit)
        if not tmdb_ids:
            return {
                "users": request.users,
                "query": request.query,
                "year": request.year,
                "recommendations": [],
            }
        report = generate_group_recommendations(
            _latest_artifact(settings.ml_artifacts_dir),
            request.users,
            limit=request.limit,
            candidate_tmdb_ids=",".join(str(value) for value in tmdb_ids),
            include_watched=True,
            bottom_limit=0,
        )
        relevance = {tmdb_id: position for position, tmdb_id in enumerate(tmdb_ids)}
        report["recommendations"].sort(
            key=lambda item: relevance.get(int(item["tmdb_id"]), len(relevance))
        )
        for rank, item in enumerate(report["recommendations"], start=1):
            item["rank"] = rank
        report["query"] = request.query
        report["search_year"] = request.year
        report["tmdb_matches"] = len(tmdb_ids)
        return _with_display_metadata(report, request.country)
    except HTTPException:
        raise
    except (ValueError, typer.BadParameter) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Group movie lookup could not be completed: {type(error).__name__}",
        ) from error


@app.get("/recommendations/{user}/scopes")
def recommendation_scopes(user: str) -> dict:
    try:
        return available_recommendation_scopes(settings.ml_artifacts_dir, user)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RecommendationReportNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/recommendations/{user}")
def recommendations(
    user: str,
    scope: str = Query(default="all"),
    year_min: int | None = Query(default=None, ge=1870, le=2200),
    year_max: int | None = Query(default=None, ge=1870, le=2200),
    runtime_min: int | None = Query(default=None, ge=1, le=600),
    runtime_max: int | None = Query(default=None, ge=1, le=600),
    genre: str | None = Query(default=None, max_length=60),
    metadata_category: str | None = Query(default=None, max_length=30),
    metadata_value: str | None = Query(default=None, max_length=200),
    metadata_filters: str | None = Query(default=None, max_length=3000),
    title_filter: str | None = Query(default=None, max_length=120),
    certification: str | None = Query(default=None, max_length=20),
    availability: str = Query(default="all", pattern=r"^(all|listed|subscription|free|rent_buy)$"),
    popularity: str = Query(default="all"),
    media_type: str = Query(default="all", pattern=r"^(all|movie|tv)$"),
    country: str = Query(default="US", pattern=r"^[A-Z]{2}$"),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    try:
        selected_metadata_filters = _parse_metadata_filters(metadata_filters)
        if metadata_category and metadata_value:
            selected_metadata_filters.append(
                {"category": metadata_category, "value": metadata_value}
            )
        if any(
            (
                media_type != "all",
                bool(selected_metadata_filters),
                bool(title_filter),
                certification not in {None, "all"},
                availability != "all",
                popularity != "all",
            )
        ):
            expanded_candidate_ids, discovery_coverage = _discover_filtered_candidate_ids(
                selected_metadata_filters,
                title_filter,
                media_type,
                year_min=year_min,
                year_max=year_max,
                runtime_min=runtime_min,
                runtime_max=runtime_max,
                genre=genre,
                certification=certification,
                availability=availability,
                popularity=popularity,
            )
            report = generate_recommendations(
                _latest_artifact(settings.ml_artifacts_dir),
                user=user,
                limit=limit,
                scope=scope,
                year_min=year_min,
                year_max=year_max,
                runtime_min=runtime_min,
                runtime_max=runtime_max,
                genre=genre,
                popularity_tier=popularity,
                metadata_category=metadata_category,
                metadata_value=metadata_value,
                metadata_filters=(
                    json.dumps(selected_metadata_filters) if selected_metadata_filters else None
                ),
                media_type=media_type,
                candidate_tmdb_ids=_candidate_ids_argument(expanded_candidate_ids),
                live_tmdb=media_type == "tv",
                persist=False,
                emit=False,
            )
            if discovery_coverage:
                discovery_coverage["candidates_scored"] = int(
                    report.get("candidates_considered") or 0
                )
                report["discovery_coverage"] = discovery_coverage
            return _with_display_metadata(report, country)
        report = load_recommendation_report(
            settings.ml_artifacts_dir,
            user,
            scope=scope,
            year_min=year_min,
            year_max=year_max,
            runtime_min=runtime_min,
            runtime_max=runtime_max,
            genre=genre,
            media_type=media_type,
            limit=limit,
        )
        return _with_display_metadata(report, country)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RecommendationReportNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/profiles/import")
async def import_profile(
    user: Annotated[str, Form()],
    archive: Annotated[UploadFile, File()],
) -> dict:
    """Import a Letterboxd ZIP locally, then map its titles to TMDB."""
    from app.services.recommendation_reports import VALID_USER

    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Use only letters, numbers, - or _ for profile")
    if not archive.filename or not archive.filename.casefold().endswith(".zip"):
        raise HTTPException(status_code=422, detail="Select a Letterboxd .zip export")
    max_bytes = 100 * 1024 * 1024
    size = 0
    try:
        with TemporaryDirectory(prefix="letterboxd-import-") as directory:
            target = Path(directory) / "letterboxd.zip"
            with target.open("wb") as handle:
                while chunk := await archive.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(status_code=413, detail="Export exceeds 100 MB")
                    handle.write(chunk)
            with SessionLocal() as session:
                imported = import_letterboxd_archive(session, target, user)
                totals = {"processed": 0, "matched": 0, "ambiguous": 0, "unresolved": 0}
                mapping_warning = None
                portable_mapping_restored = restore_profile_archive(
                    session,
                    target,
                    user,
                    settings.processed_data_dir / "tmdb-rich-details.json",
                )
                totals["matched"] += portable_mapping_restored
                local = map_pending_from_artifact(
                    session,
                    imported.user_id,
                    _latest_artifact(settings.ml_artifacts_dir),
                    settings.processed_data_dir / "tmdb-rich-details.json",
                )
                totals["matched"] += local.matched
                client = TmdbClient(settings.tmdb_api_key) if settings.tmdb_api_key else None
                if client is None:
                    mapping_warning = (
                        "Live TMDB mapping is unavailable; exact backup mappings and the "
                        "bundled catalog were used. Unmapped films remain safely pending."
                    )
                else:
                    try:
                        while True:
                            batch = map_pending_letterboxd(
                                session,
                                client,
                                imported.user_id,
                                limit=100,
                                ttl_seconds=settings.tmdb_cache_ttl_seconds,
                            )
                            for key in totals:
                                totals[key] += getattr(batch, key)
                            if batch.processed < 100:
                                break
                        direct = resolve_letterboxd_links(session, client, imported.user_id)
                        totals["matched"] += direct.matched
                        mapped_tmdb_ids = {
                            int(value)
                            for value in session.scalars(
                                select(Movie.tmdb_id)
                                .join(ImportMapping, ImportMapping.movie_id == Movie.id)
                                .where(
                                    ImportMapping.user_id == imported.user_id,
                                    ImportMapping.rating.is_not(None),
                                    Movie.tmdb_id.is_not(None),
                                )
                            )
                        }
                        load_or_fetch_details(
                            client,
                            mapped_tmdb_ids,
                            settings.processed_data_dir / "tmdb-rich-details.json",
                        )
                    except RetryError:
                        mapping_warning = (
                            "The export was imported, but TMDB mapping could not reach "
                            "the network. "
                            "Unmapped films remain safely pending."
                        )
                    finally:
                        client.close()
            review_policy = refresh_review_policy(
                user,
                settings.processed_data_dir / "tmdb-rich-details.json",
                settings.processed_data_dir / "review-policies" / f"{user}.json",
            )
            clear_group_recommendation_cache()
    except HTTPException:
        raise
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await archive.close()
    return {
        "user": user,
        "import": asdict(imported),
        "mapping": totals,
        "local_mapping": asdict(local),
        "portable_mapping_restored": portable_mapping_restored,
        "latest_review_only": True,
        "rewatch_count_retained": True,
        "archive_retained": False,
        "mapping_complete": mapping_warning is None,
        "mapping_warning": mapping_warning,
        "review_signal_policy": review_policy,
    }


@app.post("/recommendations/{user}/refresh")
def refresh_recommendations(
    user: str,
    year_min: int | None = Query(default=None, ge=1870, le=2200),
    year_max: int | None = Query(default=None, ge=1870, le=2200),
    runtime_min: int | None = Query(default=None, ge=1, le=600),
    runtime_max: int | None = Query(default=None, ge=1, le=600),
    limit: int = Query(default=20, ge=1, le=100),
    popularity: str = Query(default="all"),
    genre: str | None = Query(default=None, max_length=60),
    metadata_category: str | None = Query(default=None, max_length=30),
    metadata_value: str | None = Query(default=None, max_length=200),
    metadata_filters: str | None = Query(default=None, max_length=3000),
    title_filter: str | None = Query(default=None, max_length=120),
    certification: str | None = Query(default=None, max_length=20),
    availability: str = Query(default="all", pattern=r"^(all|listed|subscription|free|rent_buy)$"),
    media_type: str = Query(default="all", pattern=r"^(all|movie|tv)$"),
    country: str = Query(default="US", pattern=r"^[A-Z]{2}$"),
) -> dict:
    """Rebuild the combined historical/current ranking for one imported profile."""
    try:
        refresh_review_policy(
            user,
            settings.processed_data_dir / "tmdb-rich-details.json",
            settings.processed_data_dir / "review-policies" / f"{user}.json",
        )
        clear_group_recommendation_cache()
        selected_metadata_filters = _parse_metadata_filters(metadata_filters)
        if metadata_category and metadata_value:
            selected_metadata_filters.append(
                {"category": metadata_category, "value": metadata_value}
            )
        expanded_candidate_ids, discovery_coverage = _discover_filtered_candidate_ids(
            selected_metadata_filters,
            title_filter,
            media_type,
            year_min=year_min,
            year_max=year_max,
            runtime_min=runtime_min,
            runtime_max=runtime_max,
            genre=genre,
            certification=certification,
            availability=availability,
            popularity=popularity,
        )
        report = generate_recommendations(
            _latest_artifact(settings.ml_artifacts_dir),
            user=user,
            limit=limit,
            scope="all",
            year_min=year_min,
            year_max=year_max,
            runtime_min=runtime_min,
            runtime_max=runtime_max,
            popularity_tier=popularity,
            genre=genre,
            metadata_category=metadata_category,
            metadata_value=metadata_value,
            metadata_filters=(
                json.dumps(selected_metadata_filters) if selected_metadata_filters else None
            ),
            media_type=media_type,
            candidate_tmdb_ids=_candidate_ids_argument(expanded_candidate_ids),
            live_tmdb=False,
            persist=not (selected_metadata_filters or title_filter),
            emit=False,
        )
        if discovery_coverage:
            discovery_coverage["candidates_scored"] = int(report.get("candidates_considered") or 0)
            report["discovery_coverage"] = discovery_coverage
        return _with_display_metadata(report, country)
    except (ValueError, typer.BadParameter) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        # The UI must always receive JSON, including for unexpected local/runtime failures.
        raise HTTPException(
            status_code=500,
            detail=f"Ranking could not be rebuilt: {type(error).__name__}",
        ) from error


@app.get("/movies/search/{user}")
def search_movie_scores(
    user: str,
    q: str = Query(min_length=2, max_length=120),
    year: int | None = Query(default=None, ge=1870, le=2200),
    limit: int = Query(default=10, ge=1, le=25),
    country: str = Query(default="US", pattern=r"^[A-Z]{2}$"),
) -> dict:
    """Search TMDB and score exact title matches for one profile."""
    try:
        tmdb_ids = _tmdb_search_ids(q, year, limit)
        if not tmdb_ids:
            return {
                "user": user,
                "query": q,
                "year": year,
                "matches_scored": 0,
                "results": [],
            }
        report = generate_recommendations(
            _latest_artifact(settings.ml_artifacts_dir),
            user=user,
            limit=limit,
            scope="all",
            candidate_tmdb_ids=",".join(str(value) for value in tmdb_ids),
            include_watched=True,
            live_tmdb=False,
            persist=False,
            emit=False,
        )
        relevance = {tmdb_id: position for position, tmdb_id in enumerate(tmdb_ids)}
        scored = sorted(
            report["recommendations"],
            key=lambda item: relevance.get(int(item["tmdb_id"]), len(relevance)),
        )
        for rank, item in enumerate(scored, start=1):
            item["rank"] = rank
        result = {
            "user": user,
            "query": q,
            "year": year,
            "matches_scored": len(scored),
            "results": scored,
        }
        return _with_display_metadata(result, country)
    except HTTPException:
        raise
    except (ValueError, typer.BadParameter) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Movie lookup could not be completed: {type(error).__name__}",
        ) from error
