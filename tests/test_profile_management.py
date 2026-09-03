from importlib import import_module
from pathlib import Path

from app.db.models import ImportMapping, ImportRun, Movie, User
from app.main import app, settings
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    for table in (User.__table__, Movie.__table__, ImportRun.__table__, ImportMapping.__table__):
        table.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_profile_can_be_renamed_and_deleted(tmp_path: Path, monkeypatch) -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        target = User(slug="target", display_name="Target")
        survivor = User(slug="survivor", display_name="Survivor")
        session.add_all([target, survivor])
        session.flush()
        session.add(
            ImportMapping(
                user_id=target.id,
                source="letterboxd",
                source_key="movie-1",
                title="Movie One",
                year=2001,
                status="pending",
                rating=4.0,
                review_text="Rated review",
                watched=True,
                rewatch_count=1,
                watchlisted=False,
            )
        )
        session.add(
            ImportMapping(
                user_id=target.id,
                source="letterboxd",
                source_key="movie-2",
                title="Unrated Movie",
                year=2002,
                status="pending",
                rating=None,
                review_text="Must not count",
                watched=True,
                rewatch_count=0,
                watchlisted=False,
            )
        )
        session.commit()

    main_module = import_module("app.main")
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    original_artifacts = settings.ml_artifacts_dir
    original_data = settings.data_dir
    settings.ml_artifacts_dir = tmp_path / "artifacts"
    settings.data_dir = tmp_path / "data"
    ranking_dir = settings.ml_artifacts_dir / "model" / "recommendations" / "target"
    ranking_dir.mkdir(parents=True)
    (ranking_dir / "all.json").write_text("{}", encoding="utf-8")
    policy = settings.processed_data_dir / "review-policies" / "target.json"
    policy.parent.mkdir(parents=True)
    policy.write_text("{}", encoding="utf-8")

    try:
        client = TestClient(app)
        renamed = client.patch("/profiles/target", json={"display_name": "Movie Fan"})
        stats = client.get("/profiles/target/stats")
        rejected = client.request("DELETE", "/profiles/target", json={"confirmation": "wrong"})
        deleted = client.request("DELETE", "/profiles/target", json={"confirmation": "Movie Fan"})
    finally:
        settings.ml_artifacts_dir = original_artifacts
        settings.data_dir = original_data

    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "Movie Fan"
    assert stats.status_code == 200
    assert stats.json()["rated_films"] == 1
    assert stats.json()["rated_reviews"] == 1
    assert stats.json()["rewatches"] == 1
    assert rejected.status_code == 422
    assert deleted.status_code == 200
    assert not ranking_dir.exists()
    assert not policy.exists()
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(ImportMapping)) == 0
