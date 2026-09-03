from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import ImportMapping
from app.services.tmdb_mapping import MovieSearchClient


class MovieDetailsClient(MovieSearchClient):
    def movie_details(self, tmdb_id: int) -> dict: ...


@dataclass(frozen=True)
class EnrichedCandidate:
    requested_tmdb_id: int
    tmdb_id: int
    title: str
    original_title: str
    release_date: str | None
    runtime: int | None
    original_language: str | None
    genres: tuple[str, ...]
    overview: str
    popularity: float
    vote_count: int
    vote_average: float
    review_overlap_terms: tuple[str, ...]


@dataclass(frozen=True)
class EnrichedMapping:
    mapping_id: int
    title: str
    year: int | None
    candidates: tuple[EnrichedCandidate, ...]


_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "been",
    "being",
    "could",
    "from",
    "have",
    "into",
    "just",
    "like",
    "movie",
    "really",
    "some",
    "that",
    "their",
    "there",
    "they",
    "this",
    "very",
    "what",
    "when",
    "which",
    "with",
    "would",
}


def _terms(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-zA-Z]{4,}", value.casefold()) if token not in _STOPWORDS
    }


def enrich_ambiguous_mapping(
    session: Session, client: MovieDetailsClient, mapping_id: int
) -> EnrichedMapping:
    mapping = session.get(ImportMapping, mapping_id)
    if mapping is None or mapping.status != "ambiguous":
        raise ValueError(f"Mapping {mapping_id} is not an ambiguous mapping")
    review_terms = _terms(mapping.review_text or "")
    candidates: list[EnrichedCandidate] = []
    raw_candidates = json.loads(mapping.candidates_json or "[]")
    for candidate in raw_candidates:
        details = client.movie_details(int(candidate["tmdb_id"]))
        overview = details.get("overview") or ""
        candidate["canonical_tmdb_id"] = int(details["id"])
        candidates.append(
            EnrichedCandidate(
                requested_tmdb_id=int(candidate["tmdb_id"]),
                tmdb_id=int(details["id"]),
                title=details.get("title") or "",
                original_title=details.get("original_title") or "",
                release_date=details.get("release_date") or None,
                runtime=details.get("runtime"),
                original_language=details.get("original_language"),
                genres=tuple(item["name"] for item in details.get("genres", [])),
                overview=overview,
                popularity=float(details.get("popularity") or 0),
                vote_count=int(details.get("vote_count") or 0),
                vote_average=float(details.get("vote_average") or 0),
                review_overlap_terms=tuple(sorted(review_terms.intersection(_terms(overview)))),
            )
        )
    mapping.candidates_json = json.dumps(raw_candidates)
    session.commit()
    candidates.sort(key=lambda item: item.vote_count, reverse=True)
    return EnrichedMapping(mapping.id, mapping.title, mapping.year, tuple(candidates))
