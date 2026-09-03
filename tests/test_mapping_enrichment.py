import json

from app.db.base import Base
from app.db.models import ImportMapping, User
from app.services.mapping_enrichment import enrich_ambiguous_mapping
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class FakeDetailsClient:
    def search_movie(self, title: str, year: int | None = None) -> list[dict]:
        return []

    def movie_details(self, tmdb_id: int) -> dict:
        return {
            "id": tmdb_id,
            "title": "Flow",
            "original_title": "Straume",
            "release_date": "2024-08-29",
            "runtime": 85,
            "original_language": "lv",
            "genres": [{"name": "Animation"}],
            "overview": "A solitary cat survives a great flood.",
            "popularity": 10,
            "vote_count": tmdb_id,
            "vote_average": 8.1,
        }


def test_enrichment_adds_details_and_local_review_overlap() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__, ImportMapping.__table__])
    with Session(engine) as session:
        user = User(slug="default", display_name="Default")
        session.add(user)
        session.flush()
        mapping = ImportMapping(
            user_id=user.id,
            source="letterboxd",
            source_key="flow:2024",
            title="Flow",
            year=2024,
            status="ambiguous",
            review_text="The cat and flood imagery worked beautifully.",
            candidates_json=json.dumps(
                [
                    {"tmdb_id": 20, "title": "Flow", "year": 2024, "confidence": 1},
                    {"tmdb_id": 10, "title": "Flow", "year": 2024, "confidence": 1},
                ]
            ),
        )
        session.add(mapping)
        session.commit()
        result = enrich_ambiguous_mapping(session, FakeDetailsClient(), mapping.id)
    assert result.candidates[0].requested_tmdb_id == 20
    assert result.candidates[0].tmdb_id == 20
    assert result.candidates[0].review_overlap_terms == ("flood",)
