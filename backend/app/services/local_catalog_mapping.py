from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ImportMapping
from app.services.tmdb_mapping import canonical_movie, upsert_interaction
from ingestion.letterboxd.parser import normalize_title
from ingestion.tmdb.client import MatchCandidate


@dataclass(frozen=True)
class LocalMappingResult:
    pending_considered: int
    matched: int
    ambiguous: int
    unavailable: int


def _candidate_index(catalog: pd.DataFrame, cache_path: Path) -> dict[tuple[str, int | None], set]:
    index: dict[tuple[str, int | None], set[tuple[int, str, int | None]]] = {}
    for row in catalog[catalog["tmdb_id"].notna()].itertuples():
        year = int(row.year) if pd.notna(row.year) else None
        key = (normalize_title(str(row.clean_title)), year)
        index.setdefault(key, set()).add((int(row.tmdb_id), str(row.clean_title), year))
    if cache_path.is_file():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        for raw_id, details in cached.items():
            if details.get("missing") is True:
                continue
            release = details.get("release_date") or ""
            year = int(release[:4]) if release[:4].isdigit() else None
            for title in {details.get("title"), details.get("original_title")}:
                if title:
                    key = (normalize_title(str(title)), year)
                    index.setdefault(key, set()).add((int(raw_id), str(title), year))
    return index


def map_pending_from_local_catalog(
    session: Session,
    user_id: int,
    catalog: pd.DataFrame,
    cache_path: Path,
) -> LocalMappingResult:
    index = _candidate_index(catalog, cache_path)
    mappings = session.scalars(
        select(ImportMapping).where(
            ImportMapping.user_id == user_id,
            ImportMapping.source == "letterboxd",
            ImportMapping.status == "pending",
        )
    ).all()
    matched = ambiguous = unavailable = 0
    for mapping in mappings:
        candidates_by_id = {
            candidate[0]: candidate
            for candidate in index.get((normalize_title(mapping.title), mapping.year), set())
        }
        candidates = sorted(candidates_by_id.values())
        if len(candidates) == 1:
            tmdb_id, title, year = candidates[0]
            candidate = MatchCandidate(tmdb_id, title, year, 1.0)
            movie = canonical_movie(session, candidate)
            mapping.movie_id = movie.id
            mapping.status = "matched_local"
            mapping.confidence = Decimal("1.0")
            mapping.candidates_json = json.dumps(
                [{"tmdb_id": tmdb_id, "title": title, "year": year, "confidence": 1.0}]
            )
            upsert_interaction(session, mapping, movie)
            matched += 1
        elif len(candidates) > 1:
            ambiguous += 1
        else:
            unavailable += 1
    session.commit()
    return LocalMappingResult(len(mappings), matched, ambiguous, unavailable)


def map_pending_from_artifact(
    session: Session,
    user_id: int,
    artifact_dir: Path,
    cache_path: Path,
) -> LocalMappingResult:
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    catalog = pd.read_csv(artifact_dir / manifest["files"]["catalog"])
    return map_pending_from_local_catalog(session, user_id, catalog, cache_path)
