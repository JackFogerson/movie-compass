from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ImportMapping, Movie, User
from app.services.tmdb_mapping import canonical_movie, upsert_interaction
from ingestion.letterboxd.parser import normalize_title
from ingestion.tmdb.client import MatchCandidate, is_tv_catalog_id, tv_catalog_id


def _csv_bytes(fieldnames: list[str], rows: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def _read_details_cache(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _merge_details_cache(path: Path | None, imported: dict) -> int:
    if path is None or not isinstance(imported, dict) or not imported:
        return 0
    existing = _read_details_cache(path)
    restored = 0
    for key, value in imported.items():
        if not str(key).lstrip("-").isdigit() or not isinstance(value, dict):
            continue
        existing[str(key)] = value
        restored += 1
    if restored:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(existing), encoding="utf-8")
        temporary.replace(path)
    return restored


def build_profile_archive(
    session: Session,
    user: str,
    details_cache_path: Path | None = None,
) -> tuple[bytes, str, int]:
    """Build a Letterboxd-compatible, rating-only backup for one profile."""
    owner = session.scalar(select(User).where(User.slug == user))
    if owner is None:
        raise LookupError("Profile not found")

    rows = session.execute(
        select(ImportMapping, Movie.tmdb_id)
        .outerjoin(Movie, Movie.id == ImportMapping.movie_id)
        .where(
            ImportMapping.user_id == owner.id,
            ImportMapping.rating.is_not(None),
        )
        .order_by(ImportMapping.title, ImportMapping.year)
    ).all()
    if not rows:
        raise ValueError("This profile has no rated films to export")

    ratings: list[dict] = []
    watched: list[dict] = []
    reviews: list[dict] = []
    diary: list[dict] = []
    manifest_movies: list[dict] = []
    for mapping, tmdb_id in rows:
        media_type = "tv" if tmdb_id is not None and is_tv_catalog_id(tmdb_id) else "movie"
        external_tmdb_id = abs(tmdb_id) if tmdb_id is not None else None
        watched_date = mapping.watched_date.isoformat() if mapping.watched_date else ""
        letterboxd_uri = (
            mapping.source_key if str(mapping.source_key).startswith("http") else ""
        )
        common = {
            "Date": watched_date,
            "Name": mapping.title,
            "Year": mapping.year or "",
            "Letterboxd URI": letterboxd_uri,
            "TMDB ID": external_tmdb_id or "",
        }
        ratings.append({**common, "Rating": float(mapping.rating)})
        watched.append(common)
        if (mapping.review_text or "").strip():
            reviews.append({**common, "Review": mapping.review_text.strip()})
        for _ in range(int(mapping.rewatch_count or 0)):
            diary.append({**common, "Rewatch": "Yes"})
        manifest_movies.append(
            {
                "title": mapping.title,
                "year": mapping.year,
                "tmdb_id": external_tmdb_id,
                "media_type": media_type,
                "rating": float(mapping.rating),
                "review_text": (mapping.review_text or "").strip() or None,
                "watched_date": watched_date or None,
                "rewatch_count": int(mapping.rewatch_count or 0),
            }
        )

    manifest = {
        "format": "movie-compass-profile",
        "version": 2,
        "profile_id": owner.slug,
        "display_name": owner.display_name,
        "exported_at": datetime.now(UTC).isoformat(),
        "rated_films": len(rows),
        "movies": manifest_movies,
    }
    archive = io.BytesIO()
    details_cache = _read_details_cache(details_cache_path)
    profile_details = {
        str(movie["tmdb_id"] if movie["media_type"] == "movie" else -movie["tmdb_id"]): (
            details_cache[
                str(movie["tmdb_id"] if movie["media_type"] == "movie" else -movie["tmdb_id"])
            ]
        )
        for movie in manifest_movies
        if movie["tmdb_id"] is not None
        and str(movie["tmdb_id"] if movie["media_type"] == "movie" else -movie["tmdb_id"])
        in details_cache
    }
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "ratings.csv",
            _csv_bytes(
                ["Date", "Name", "Year", "Letterboxd URI", "Rating", "TMDB ID"],
                ratings,
            ),
        )
        bundle.writestr(
            "watched.csv",
            _csv_bytes(["Date", "Name", "Year", "Letterboxd URI", "TMDB ID"], watched),
        )
        bundle.writestr(
            "reviews.csv",
            _csv_bytes(
                ["Date", "Name", "Year", "Letterboxd URI", "Review", "TMDB ID"],
                reviews,
            ),
        )
        bundle.writestr(
            "diary.csv",
            _csv_bytes(
                ["Date", "Name", "Year", "Letterboxd URI", "Rewatch", "TMDB ID"],
                diary,
            ),
        )
        bundle.writestr(
            "movie-compass-profile.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        bundle.writestr(
            "movie-compass-metadata.json",
            json.dumps(profile_details, ensure_ascii=False).encode("utf-8"),
        )
    return archive.getvalue(), f"movie-compass-{owner.slug}.zip", len(rows)


def restore_profile_archive(
    session: Session,
    archive_path: Path,
    user: str,
    details_cache_path: Path | None = None,
) -> int:
    """Restore exact TMDB mappings and display name from a Movie Compass backup."""
    try:
        with zipfile.ZipFile(archive_path) as bundle:
            if "movie-compass-profile.json" not in bundle.namelist():
                return 0
            manifest = json.loads(bundle.read("movie-compass-profile.json"))
            metadata = (
                json.loads(bundle.read("movie-compass-metadata.json"))
                if "movie-compass-metadata.json" in bundle.namelist()
                else {}
            )
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError):
        return 0
    if manifest.get("format") != "movie-compass-profile" or manifest.get("version") not in {1, 2}:
        return 0
    _merge_details_cache(details_cache_path, metadata)

    owner = session.scalar(select(User).where(User.slug == user))
    if owner is None:
        return 0
    display_name = str(manifest.get("display_name") or "").strip()
    if display_name:
        owner.display_name = display_name[:200]
    mappings = session.scalars(
        select(ImportMapping).where(
            ImportMapping.user_id == owner.id,
            ImportMapping.rating.is_not(None),
        )
    ).all()
    mapping_index = {
        (normalize_title(mapping.title), mapping.year): mapping for mapping in mappings
    }
    restored = 0
    for item in manifest.get("movies", []):
        external_tmdb_id = item.get("tmdb_id")
        if not isinstance(external_tmdb_id, int) or external_tmdb_id <= 0:
            continue
        media_type = "tv" if item.get("media_type") == "tv" else "movie"
        tmdb_id = (
            tv_catalog_id(external_tmdb_id) if media_type == "tv" else external_tmdb_id
        )
        year = item.get("year") if isinstance(item.get("year"), int) else None
        mapping = mapping_index.get((normalize_title(str(item.get("title") or "")), year))
        if mapping is None:
            continue
        movie = canonical_movie(
            session,
            MatchCandidate(tmdb_id, mapping.title, mapping.year, 1.0),
        )
        mapping.movie_id = movie.id
        mapping.status = "matched_manual"
        mapping.confidence = Decimal("1.0")
        mapping.candidates_json = json.dumps(
            [
                {
                    "tmdb_id": tmdb_id,
                    "title": mapping.title,
                    "year": mapping.year,
                    "confidence": 1.0,
                    "source": "movie_compass_backup",
                    "media_type": media_type,
                }
            ]
        )
        upsert_interaction(session, mapping, movie)
        restored += 1
    session.commit()
    return restored
