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
from ingestion.tmdb.client import MatchCandidate


def _csv_bytes(fieldnames: list[str], rows: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def build_profile_archive(session: Session, user: str) -> tuple[bytes, str, int]:
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
        watched_date = mapping.watched_date.isoformat() if mapping.watched_date else ""
        letterboxd_uri = (
            mapping.source_key if str(mapping.source_key).startswith("http") else ""
        )
        common = {
            "Date": watched_date,
            "Name": mapping.title,
            "Year": mapping.year or "",
            "Letterboxd URI": letterboxd_uri,
            "TMDB ID": tmdb_id or "",
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
                "tmdb_id": tmdb_id,
                "rating": float(mapping.rating),
                "review_text": (mapping.review_text or "").strip() or None,
                "watched_date": watched_date or None,
                "rewatch_count": int(mapping.rewatch_count or 0),
            }
        )

    manifest = {
        "format": "movie-compass-profile",
        "version": 1,
        "profile_id": owner.slug,
        "display_name": owner.display_name,
        "exported_at": datetime.now(UTC).isoformat(),
        "rated_films": len(rows),
        "movies": manifest_movies,
    }
    archive = io.BytesIO()
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
    return archive.getvalue(), f"movie-compass-{owner.slug}.zip", len(rows)


def restore_profile_archive(session: Session, archive_path: Path, user: str) -> int:
    """Restore exact TMDB mappings and display name from a Movie Compass backup."""
    try:
        with zipfile.ZipFile(archive_path) as bundle:
            if "movie-compass-profile.json" not in bundle.namelist():
                return 0
            manifest = json.loads(bundle.read("movie-compass-profile.json"))
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError):
        return 0
    if manifest.get("format") != "movie-compass-profile" or manifest.get("version") != 1:
        return 0

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
        tmdb_id = item.get("tmdb_id")
        if not isinstance(tmdb_id, int) or tmdb_id <= 0:
            continue
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
                }
            ]
        )
        upsert_interaction(session, mapping, movie)
        restored += 1
    session.commit()
    return restored
