from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import ImportMapping, MappingDecision
from app.services.tmdb_mapping import canonical_movie, upsert_interaction
from ingestion.tmdb.client import MatchCandidate


class MappingReviewError(ValueError):
    pass


@dataclass(frozen=True)
class MappingDecisionResult:
    mapping_id: int
    action: str
    previous_status: str
    status: str
    tmdb_id: int | None


def _mapping_for_review(session: Session, mapping_id: int) -> ImportMapping:
    mapping = session.get(ImportMapping, mapping_id)
    if mapping is None:
        raise MappingReviewError(f"Mapping {mapping_id} does not exist")
    if mapping.status not in {"pending", "ambiguous", "unresolved", "rejected"}:
        raise MappingReviewError(
            f"Mapping {mapping_id} has status {mapping.status!r} and is not reviewable"
        )
    return mapping


def approve_mapping(
    session: Session,
    mapping_id: int,
    tmdb_id: int,
    *,
    actor: str = "local-user",
    reason: str | None = None,
) -> MappingDecisionResult:
    mapping = _mapping_for_review(session, mapping_id)
    candidates = json.loads(mapping.candidates_json or "[]")
    selected = next(
        (
            item
            for item in candidates
            if int(item["tmdb_id"]) == tmdb_id
            or int(item.get("canonical_tmdb_id", item["tmdb_id"])) == tmdb_id
        ),
        None,
    )
    if selected is None:
        raise MappingReviewError(
            f"TMDB movie {tmdb_id} is not among the recorded candidates for mapping {mapping_id}"
        )
    previous = mapping.status
    candidate = MatchCandidate(
        tmdb_id=int(selected.get("canonical_tmdb_id", tmdb_id)),
        title=str(selected["title"]),
        year=selected.get("year"),
        confidence=float(selected["confidence"]),
    )
    movie = canonical_movie(session, candidate)
    mapping.movie_id = movie.id
    mapping.status = "matched_manual"
    mapping.confidence = candidate.confidence
    mapping.updated_at = datetime.now(UTC)
    upsert_interaction(session, mapping, movie)
    session.add(
        MappingDecision(
            mapping_id=mapping.id,
            action="approve",
            previous_status=previous,
            tmdb_id=candidate.tmdb_id,
            actor=actor,
            reason=reason,
        )
    )
    session.commit()
    return MappingDecisionResult(mapping.id, "approve", previous, mapping.status, candidate.tmdb_id)


def reject_mapping(
    session: Session,
    mapping_id: int,
    *,
    actor: str = "local-user",
    reason: str | None = None,
) -> MappingDecisionResult:
    mapping = _mapping_for_review(session, mapping_id)
    previous = mapping.status
    mapping.status = "rejected"
    mapping.movie_id = None
    mapping.updated_at = datetime.now(UTC)
    session.add(
        MappingDecision(
            mapping_id=mapping.id,
            action="reject",
            previous_status=previous,
            actor=actor,
            reason=reason,
        )
    )
    session.commit()
    return MappingDecisionResult(mapping.id, "reject", previous, mapping.status, None)
