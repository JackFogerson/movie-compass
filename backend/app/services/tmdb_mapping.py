from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ImportMapping, Movie, TmdbSearchCache, UserMovieInteraction
from ingestion.tmdb.client import MatchCandidate, match_movie


class MovieSearchClient(Protocol):
    def search_movie(self, title: str, year: int | None = None) -> list[dict]: ...

    def movie_details(self, tmdb_id: int, append_to_response: str | None = None) -> dict: ...

    def letterboxd_tmdb_id(self, source_url: str) -> int | None: ...


@dataclass(frozen=True)
class MappingBatchResult:
    processed: int
    matched: int
    ambiguous: int
    unresolved: int
    cache_hits: int


def _cache_key(title: str, year: int | None) -> str:
    value = json.dumps([title.casefold().strip(), year], separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def _cached_search(
    session: Session,
    client: MovieSearchClient,
    title: str,
    year: int | None,
    ttl_seconds: int,
) -> tuple[list[dict], bool]:
    key = _cache_key(title, year)
    now = datetime.now(UTC)
    cached = session.scalar(
        select(TmdbSearchCache).where(
            TmdbSearchCache.cache_key == key,
            TmdbSearchCache.expires_at > now,
        )
    )
    if cached:
        return json.loads(cached.response_json), True
    results = client.search_movie(title, year)
    cached = session.scalar(select(TmdbSearchCache).where(TmdbSearchCache.cache_key == key))
    if cached is None:
        cached = TmdbSearchCache(cache_key=key, query_title=title, query_year=year)
        session.add(cached)
    cached.response_json = json.dumps(results)
    cached.fetched_at = now
    cached.expires_at = now + timedelta(seconds=ttl_seconds)
    return results, False


def canonical_movie(session: Session, candidate: MatchCandidate) -> Movie:
    movie = session.scalar(select(Movie).where(Movie.tmdb_id == candidate.tmdb_id))
    if movie is None:
        movie = Movie(
            tmdb_id=candidate.tmdb_id,
            title=candidate.title,
            original_title=candidate.title,
            year=candidate.year,
        )
        session.add(movie)
        session.flush()
    return movie


def upsert_interaction(session: Session, mapping: ImportMapping, movie: Movie) -> None:
    interaction = session.scalar(
        select(UserMovieInteraction).where(
            UserMovieInteraction.user_id == mapping.user_id,
            UserMovieInteraction.movie_id == movie.id,
        )
    )
    if interaction is None:
        interaction = UserMovieInteraction(
            user_id=mapping.user_id, movie_id=movie.id, source="letterboxd"
        )
        session.add(interaction)
    interaction.rating = Decimal(str(mapping.rating)) if mapping.rating is not None else None
    interaction.liked = mapping.liked
    interaction.watched = mapping.watched
    interaction.watched_date = mapping.watched_date
    interaction.rewatch_count = mapping.rewatch_count
    interaction.review_text = mapping.review_text
    interaction.watchlisted = mapping.watchlisted
    interaction.imported_at = datetime.now(UTC)


def _letterboxd_candidate(
    client: MovieSearchClient, mapping: ImportMapping
) -> MatchCandidate | None:
    """Use the export's Letterboxd URI to avoid guessing among same-title films."""
    resolver = getattr(client, "letterboxd_tmdb_id", None)
    detail_loader = getattr(client, "movie_details", None)
    if not callable(resolver) or not callable(detail_loader):
        return None
    try:
        tmdb_id = resolver(mapping.source_key)
        if tmdb_id is None:
            return None
    except Exception:
        return None
    try:
        details = detail_loader(tmdb_id)
    except Exception:
        # A newly created TMDB record may be linked publicly by Letterboxd before
        # it is readable through the API. The outbound ID is still exact.
        return MatchCandidate(
            tmdb_id=int(tmdb_id),
            title=mapping.title,
            year=mapping.year,
            confidence=0.99,
        )
    release = str(details.get("release_date") or "")
    year = int(release[:4]) if len(release) >= 4 and release[:4].isdigit() else mapping.year
    title = str(details.get("title") or details.get("original_title") or mapping.title)
    return MatchCandidate(tmdb_id=int(tmdb_id), title=title, year=year, confidence=1.0)


def map_pending_letterboxd(
    session: Session,
    client: MovieSearchClient,
    user_id: int,
    *,
    limit: int = 100,
    ttl_seconds: int = 2_592_000,
    retry_unresolved: bool = False,
) -> MappingBatchResult:
    statuses = ["pending"]
    if retry_unresolved:
        statuses.extend(["unresolved", "ambiguous"])
    mapping_ids = session.scalars(
        select(ImportMapping.id)
        .where(
            ImportMapping.user_id == user_id,
            ImportMapping.source == "letterboxd",
            ImportMapping.status.in_(statuses),
        )
        .order_by(ImportMapping.id)
        .limit(limit)
    ).all()
    counts = {"matched": 0, "ambiguous": 0, "unresolved": 0}
    cache_hits = 0
    for mapping_id in mapping_ids:
        mapping = session.get(ImportMapping, mapping_id)
        if mapping is None:
            continue
        results, cache_hit = _cached_search(
            session, client, mapping.title, mapping.year, ttl_seconds
        )
        cache_hits += int(cache_hit)
        match = match_movie(mapping.title, mapping.year, results)
        if match.status != "matched":
            direct = _letterboxd_candidate(client, mapping)
            if direct is not None:
                match = type(match)("matched", direct, (direct,))
        mapping.status = match.status
        mapping.confidence = Decimal(str(match.candidate.confidence)) if match.candidate else None
        mapping.candidates_json = json.dumps([asdict(item) for item in match.candidates])
        mapping.updated_at = datetime.now(UTC)
        if match.status == "matched":
            assert match.candidate is not None
            movie = canonical_movie(session, match.candidate)
            mapping.movie_id = movie.id
            upsert_interaction(session, mapping, movie)
        counts[match.status] += 1
        session.commit()
    return MappingBatchResult(
        len(mapping_ids),
        counts["matched"],
        counts["ambiguous"],
        counts["unresolved"],
        cache_hits,
    )


def resolve_letterboxd_links(
    session: Session,
    client: MovieSearchClient,
    user_id: int,
    *,
    limit: int = 10_000,
) -> MappingBatchResult:
    """Repair uncertain matches from Letterboxd's exact outbound TMDB links."""
    mappings = session.scalars(
        select(ImportMapping)
        .where(
            ImportMapping.user_id == user_id,
            ImportMapping.source == "letterboxd",
            ImportMapping.status.in_(("unresolved", "ambiguous")),
        )
        .order_by(ImportMapping.id)
        .limit(limit)
    ).all()
    matched = 0
    for mapping in mappings:
        candidate = _letterboxd_candidate(client, mapping)
        if candidate is None:
            continue
        mapping.status = "matched"
        mapping.confidence = Decimal("1.0")
        mapping.candidates_json = json.dumps([asdict(candidate)])
        mapping.updated_at = datetime.now(UTC)
        movie = canonical_movie(session, candidate)
        mapping.movie_id = movie.id
        upsert_interaction(session, mapping, movie)
        matched += 1
    session.commit()
    remaining = len(mappings) - matched
    return MappingBatchResult(len(mappings), matched, 0, remaining, 0)
