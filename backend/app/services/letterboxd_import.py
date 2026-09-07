from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import ImportMapping, ImportRun, Movie, User, UserMovieInteraction
from app.services.tmdb_mapping import upsert_interaction
from ingestion.letterboxd.parser import LetterboxdMovie, parse_export


@dataclass(frozen=True)
class PersistedImportResult:
    run_id: int
    user_id: int
    archive_sha256: str
    movies_staged: int
    created: int
    updated: int
    removed_stale: int
    already_imported: bool


def _archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _get_or_create_user(session: Session, slug: str) -> User:
    user = session.scalar(select(User).where(User.slug == slug))
    if user:
        return user
    user = User(slug=slug, display_name=slug.replace("-", " ").title())
    session.add(user)
    session.flush()
    return user


def _apply_movie(mapping: ImportMapping, movie: LetterboxdMovie) -> None:
    identity_changed = mapping.title != movie.name or mapping.year != movie.year
    mapping.title = movie.name
    mapping.year = movie.year
    mapping.rating = movie.rating
    mapping.liked = movie.liked
    mapping.watched = movie.watched
    mapping.watched_date = max(movie.watched_dates) if movie.watched_dates else None
    mapping.rewatch_count = movie.rewatch_count
    mapping.review_text = movie.review_text
    mapping.watchlisted = movie.watchlisted
    mapping.updated_at = datetime.now(UTC)
    if identity_changed and mapping.movie_id is None:
        mapping.status = "pending"
        mapping.confidence = None
        mapping.candidates_json = None


def _sync_mapped_interactions(session: Session, user_id: int) -> None:
    """Keep canonical interactions aligned when a later export changes a rating or review."""
    mappings = session.scalars(
        select(ImportMapping).where(
            ImportMapping.user_id == user_id,
            ImportMapping.rating.is_not(None),
            ImportMapping.movie_id.is_not(None),
        )
    ).all()
    for mapping in mappings:
        movie = session.get(Movie, mapping.movie_id)
        if movie is not None:
            upsert_interaction(session, mapping, movie)


def import_letterboxd_archive(
    session: Session,
    archive_path: Path,
    user_slug: str = "default",
    *,
    force: bool = False,
) -> PersistedImportResult:
    archive_hash = _archive_sha256(archive_path)
    parsed_movies, report = parse_export(archive_path)
    movies = [movie for movie in parsed_movies if movie.rating is not None]
    if not movies:
        raise ValueError("The Letterboxd export does not contain any rated films")
    user = _get_or_create_user(session, user_slug)
    session.execute(
        delete(UserMovieInteraction).where(
            UserMovieInteraction.user_id == user.id,
            UserMovieInteraction.rating.is_(None),
        )
    )
    session.execute(
        delete(ImportMapping).where(
            ImportMapping.user_id == user.id,
            ImportMapping.rating.is_(None),
        )
    )
    prior = session.scalar(
        select(ImportRun).where(
            ImportRun.user_id == user.id,
            ImportRun.source == "letterboxd",
            ImportRun.archive_sha256 == archive_hash,
        )
    )
    if prior and prior.status == "completed" and not force:
        _sync_mapped_interactions(session, user.id)
        session.commit()
        return PersistedImportResult(prior.id, user.id, archive_hash, len(movies), 0, 0, 0, True)

    run = prior or ImportRun(
        user_id=user.id,
        source="letterboxd",
        archive_sha256=archive_hash,
        archive_name=archive_path.name,
        status="running",
        report_json="{}",
    )
    session.add(run)
    created = 0
    updated = 0
    current_keys: set[str] = set()
    for movie in movies:
        current_keys.add(movie.source_key)
        mapping = session.scalar(
            select(ImportMapping).where(
                ImportMapping.user_id == user.id,
                ImportMapping.source == "letterboxd",
                ImportMapping.source_key == movie.source_key,
            )
        )
        if mapping is None:
            mapping = ImportMapping(
                user_id=user.id,
                source="letterboxd",
                source_key=movie.source_key,
                title=movie.name,
                year=movie.year,
                status="pending",
            )
            session.add(mapping)
            created += 1
        else:
            updated += 1
        _apply_movie(mapping, movie)
    session.flush()
    _sync_mapped_interactions(session, user.id)
    removed_stale = 0
    if force:
        stale = session.scalars(
            select(ImportMapping).where(
                ImportMapping.user_id == user.id,
                ImportMapping.source == "letterboxd",
                ImportMapping.movie_id.is_(None),
                ImportMapping.status.in_(["pending", "unresolved", "ambiguous", "rejected"]),
                ImportMapping.source_key.not_in(current_keys),
            )
        ).all()
        for mapping in stale:
            session.delete(mapping)
        removed_stale = len(stale)
    run.status = "completed"
    run.report_json = json.dumps(asdict(report))
    run.completed_at = datetime.now(UTC)
    session.commit()
    return PersistedImportResult(
        run.id,
        user.id,
        archive_hash,
        len(movies),
        created,
        updated,
        removed_stale,
        False,
    )
