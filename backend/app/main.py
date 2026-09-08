import csv
import gzip
import io
import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal
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
from app.services.profile_stats import build_taste_breakdown
from app.services.recommendation_reports import (
    RecommendationReportNotFound,
    _latest_artifact,
    available_recommendation_scopes,
    load_recommendation_report,
)
from app.services.review_policy import refresh_review_policy
from app.services.tmdb_mapping import map_pending_letterboxd, resolve_letterboxd_links
from ingestion.letterboxd.parser import normalize_title
from ingestion.tmdb.client import TmdbClient
from ingestion.tmdb.daily_export import load_catalog_summary
from ingestion.tmdb.details_cache import load_or_fetch_details

settings = get_settings()
configure_logging(settings.log_level)
app = FastAPI(title="Personal Movie Recommender", version="0.1.0")
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


class GroupRecommendationRequest(BaseModel):
    users: list[str] = Field(min_length=2, max_length=4)
    year_min: int | None = Field(default=None, ge=1870, le=2200)
    year_max: int | None = Field(default=None, ge=1870, le=2200)
    runtime_min: int | None = Field(default=None, ge=1, le=600)
    runtime_max: int | None = Field(default=None, ge=1, le=600)
    popularity: str = "all"
    genre: str | None = Field(default=None, max_length=60)
    country: str = Field(default="US", pattern=r"^[A-Z]{2}$")
    include_watched: bool = False
    limit: int = Field(default=20, ge=1, le=30)


class GroupMovieSearchRequest(GroupRecommendationRequest):
    query: str = Field(min_length=2, max_length=120)
    year: int | None = Field(default=None, ge=1870, le=2200)


class ProfileUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


class ProfileDeleteRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=100)


class ManualRatingRequest(BaseModel):
    tmdb_id: int = Field(gt=0)
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
            if details.get("missing") is True or not str(raw_tmdb_id).isdigit():
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


def _tmdb_search_ids(query: str, year: int | None, limit: int) -> list[int]:
    """Search TMDB, falling back to the bundled catalog after network retry failures."""
    local_ids = _local_movie_search_ids(query, year, limit)
    if not settings.tmdb_api_key:
        return local_ids
    client = TmdbClient(settings.tmdb_api_key)
    try:
        results = client.search_movie(query, year)[:limit]
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
    return {"status": "ok", "environment": settings.app_env}


@app.get("/catalog/status")
def catalog_status() -> dict:
    summary = load_catalog_summary(settings.processed_data_dir / "tmdb-catalog-manifest.json")
    return {
        "synced": summary is not None,
        "tmdb_daily_export": summary,
    }


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
def profile_stats(user: str) -> dict:
    """Return rating-only statistics for one imported profile."""
    from app.services.recommendation_reports import VALID_USER

    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.slug == user))
        if owner is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        rows = session.execute(
            select(
                ImportMapping.title,
                ImportMapping.rating,
                ImportMapping.review_text,
                ImportMapping.rewatch_count,
                ImportMapping.status,
                ImportMapping.year,
                Movie.tmdb_id,
                Movie.runtime,
            )
            .outerjoin(Movie, Movie.id == ImportMapping.movie_id)
            .where(
                ImportMapping.user_id == owner.id,
                ImportMapping.rating.is_not(None),
            )
        ).all()
        last_import = session.scalar(
            select(func.max(ImportRun.completed_at)).where(ImportRun.user_id == owner.id)
        )
    ratings = [float(row.rating) for row in rows]
    distribution = {f"{value / 2:.1f}": 0 for value in range(1, 11)}
    for rating in ratings:
        distribution[f"{rating:.1f}"] = distribution.get(f"{rating:.1f}", 0) + 1
    mapped_statuses = {"matched", "matched_local", "matched_manual"}
    details_path = settings.processed_data_dir / "tmdb-rich-details.json"
    try:
        details_raw = (
            json.loads(details_path.read_text(encoding="utf-8"))
            if details_path.is_file()
            else {}
        )
    except (OSError, json.JSONDecodeError):
        details_raw = {}
    details_by_id = {
        int(key): value for key, value in details_raw.items() if str(key).isdigit()
    }
    taste_breakdown = build_taste_breakdown(
        [
            {
                "rating": float(row.rating),
                "year": row.year,
                "tmdb_id": row.tmdb_id,
                "runtime": row.runtime,
            }
            for row in rows
        ],
        details_by_id,
    )
    return {
        "slug": owner.slug,
        "display_name": owner.display_name,
        "rated_films": len(ratings),
        "mapped_films": sum(row.status in mapped_statuses for row in rows),
        "pending_films": sum(row.status not in mapped_statuses for row in rows),
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
        "last_imported_at": last_import.isoformat() if last_import else None,
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
                json.loads(cache_path.read_text(encoding="utf-8"))
                if cache_path.is_file()
                else {}
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
            content, filename, _ = build_profile_archive(session, user)
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
        return evaluate_profile_accuracy(_latest_artifact(settings.ml_artifacts_dir), user)
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
        raise HTTPException(status_code=503, detail="TMDB_API_KEY is not configured")
    client = TmdbClient(settings.tmdb_api_key)
    try:
        results = client.search_movie(q, year)[:12]
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
    return {"results": result_rows}


@app.put("/profiles/{user}/ratings")
def save_manual_rating(user: str, request: ManualRatingRequest) -> dict:
    """Add or update one rated film and immediately refresh the personal model."""
    from app.services.recommendation_reports import VALID_USER

    if not VALID_USER.fullmatch(user):
        raise HTTPException(status_code=422, detail="Invalid profile ID")
    if not settings.tmdb_api_key:
        raise HTTPException(status_code=503, detail="TMDB_API_KEY is not configured")
    client = TmdbClient(settings.tmdb_api_key)
    try:
        details = client.movie_details(request.tmdb_id, "keywords,credits")
    except Exception as error:
        raise HTTPException(
            status_code=422, detail="That TMDB movie could not be loaded"
        ) from error
    finally:
        client.close()
    details_cache_path = settings.processed_data_dir / "tmdb-rich-details.json"
    try:
        cached_details = (
            json.loads(details_cache_path.read_text(encoding="utf-8"))
            if details_cache_path.is_file()
            else {}
        )
    except (OSError, json.JSONDecodeError):
        cached_details = {}
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
                source_key=f"tmdb:{request.tmdb_id}",
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
        "title": title,
        "rating": request.rating,
        "review_saved": review is not None,
        "ranking_updated": ranking_warning is None,
        "ranking_warning": ranking_warning,
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
            include_watched=request.include_watched,
        )
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
    country: str = Query(default="US", pattern=r"^[A-Z]{2}$"),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    try:
        report = load_recommendation_report(
            settings.ml_artifacts_dir,
            user,
            scope=scope,
            year_min=year_min,
            year_max=year_max,
            runtime_min=runtime_min,
            runtime_max=runtime_max,
            genre=genre,
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
    if not settings.tmdb_api_key:
        raise HTTPException(status_code=503, detail="TMDB_API_KEY is not configured")

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
                portable_mapping_restored = restore_profile_archive(session, target, user)
                totals["matched"] += portable_mapping_restored
                local = map_pending_from_artifact(
                    session,
                    imported.user_id,
                    _latest_artifact(settings.ml_artifacts_dir),
                    settings.processed_data_dir / "tmdb-rich-details.json",
                )
                totals["matched"] += local.matched
                client = TmdbClient(settings.tmdb_api_key)
                try:
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
            live_tmdb=False,
            persist=True,
            emit=False,
        )
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
