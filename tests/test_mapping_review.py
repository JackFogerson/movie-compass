import json
from decimal import Decimal

import pytest
from app.db.base import Base
from app.db.models import ImportMapping, MappingDecision, Movie, User, UserMovieInteraction
from app.services.mapping_review import MappingReviewError, approve_mapping, reject_mapping
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Movie.__table__,
            UserMovieInteraction.__table__,
            ImportMapping.__table__,
            MappingDecision.__table__,
        ],
    )
    return Session(engine)


def _mapping(session: Session, key: str) -> ImportMapping:
    user = session.scalar(select(User).where(User.slug == "default"))
    if user is None:
        user = User(slug="default", display_name="Default")
        session.add(user)
        session.flush()
    mapping = ImportMapping(
        user_id=user.id,
        source="letterboxd",
        source_key=key,
        title="The Thing",
        year=1982,
        status="ambiguous",
        rating=Decimal("4.5"),
        watched=True,
        candidates_json=json.dumps(
            [
                {
                    "tmdb_id": 1091,
                    "title": "The Thing",
                    "year": 1982,
                    "confidence": 1.0,
                }
            ]
        ),
    )
    session.add(mapping)
    session.commit()
    return mapping


def test_approval_is_audited_and_creates_interaction() -> None:
    session = _session()
    mapping = _mapping(session, "one")
    result = approve_mapping(session, mapping.id, 1091, actor="tester", reason="verified")
    assert result.status == "matched_manual"
    assert session.scalar(select(func.count()).select_from(MappingDecision)) == 1
    interaction = session.scalar(select(UserMovieInteraction))
    assert interaction and interaction.rating == Decimal("4.5")


def test_rejection_is_audited_and_unknown_candidate_is_refused() -> None:
    session = _session()
    mapping = _mapping(session, "two")
    with pytest.raises(MappingReviewError, match="not among"):
        approve_mapping(session, mapping.id, 999)
    result = reject_mapping(session, mapping.id, reason="wrong edition")
    assert result.status == "rejected"
    assert session.scalar(select(MappingDecision).where(MappingDecision.mapping_id == mapping.id))


def test_approval_accepts_tmdb_canonical_redirect_id() -> None:
    session = _session()
    mapping = _mapping(session, "redirect")
    candidates = json.loads(mapping.candidates_json)
    candidates[0]["canonical_tmdb_id"] = 2000
    mapping.candidates_json = json.dumps(candidates)
    session.commit()
    result = approve_mapping(session, mapping.id, 2000)
    assert result.tmdb_id == 2000
