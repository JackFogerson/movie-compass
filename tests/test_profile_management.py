import io
import json
import zipfile
from datetime import date
from importlib import import_module
from pathlib import Path

from app.db.models import ImportMapping, ImportRun, Movie, User, UserMovieInteraction
from app.main import app, settings
from app.services.profile_export import build_profile_archive, restore_profile_archive
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

    for table in (
        User.__table__,
        Movie.__table__,
        ImportRun.__table__,
        ImportMapping.__table__,
        UserMovieInteraction.__table__,
    ):
        table.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_profile_can_be_renamed_and_deleted(tmp_path: Path, monkeypatch) -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        target = User(slug="target", display_name="Target")
        survivor = User(slug="survivor", display_name="Survivor")
        session.add_all([target, survivor])
        session.flush()
        movie = Movie(tmdb_id=10, title="Movie One", year=2001)
        session.add(movie)
        session.flush()
        session.add(
            UserMovieInteraction(
                user_id=target.id,
                movie_id=movie.id,
                rating=4.0,
                review_text="Rated review",
                watched=True,
                watched_date=date(2024, 5, 1),
                rewatch_count=1,
            )
        )
        session.add(
            ImportMapping(
                user_id=target.id,
                source="letterboxd",
                source_key="movie-1",
                title="Movie One",
                year=2001,
                movie_id=movie.id,
                status="matched",
                rating=4.0,
                review_text="Rated review",
                watched=True,
                watched_date=date(2024, 5, 1),
                rewatch_count=1,
                watchlisted=False,
            )
        )
        session.add(
            ImportMapping(
                user_id=target.id,
                source="manual",
                source_key="tmdb:10",
                title="Movie One",
                year=2001,
                movie_id=movie.id,
                status="matched_manual",
                rating=4.0,
                review_text="Rated review",
                watched=True,
                rewatch_count=0,
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
    (settings.processed_data_dir / "tmdb-rich-details.json").write_text(
        json.dumps(
            {
                "10": {
                    "title": "Movie One",
                    "poster_path": "/movie-one.jpg",
                    "credits": {"cast": [{"name": "Only Actor"}], "crew": []},
                }
            }
        ),
        encoding="utf-8",
    )

    try:
        client = TestClient(app)
        renamed = client.patch("/profiles/target", json={"display_name": "Movie Fan"})
        stats = client.get("/profiles/target/stats")
        filtered_stats = client.get(
            "/profiles/target/stats?watched_year_min=2025&watched_year_max=2026"
        )
        actor_movies = client.get(
            "/profiles/target/stats/movies",
            params={"category": "actors", "value": "Only Actor"},
        )
        actor_category = client.get(
            "/profiles/target/stats/category",
            params={"category": "actors"},
        )
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
    assert stats.json()["watched_year_filter"] == {"minimum": None, "maximum": None}
    assert stats.json()["available_watched_years"] == {"minimum": 2024, "maximum": 2024}
    assert stats.json()["available_review_years"] == [2024]
    assert filtered_stats.status_code == 200
    assert filtered_stats.json()["rated_films"] == 0
    assert actor_movies.status_code == 200
    assert actor_movies.json()["count"] == 1
    assert actor_movies.json()["movies"][0]["title"] == "Movie One"
    assert actor_category.status_code == 200
    assert actor_category.json()["count"] == 1
    assert actor_category.json()["top"][0]["label"] == "Only Actor"
    assert actor_category.json()["bottom"] == []
    assert rejected.status_code == 422
    assert deleted.status_code == 200
    assert not ranking_dir.exists()
    assert not policy.exists()
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(ImportMapping)) == 0


def test_fresh_install_can_start_without_profiles(monkeypatch) -> None:
    session_factory = _session_factory()
    main_module = import_module("app.main")
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)

    response = TestClient(app).get("/profiles")

    assert response.status_code == 200
    assert response.json() == {"profiles": []}


def test_profile_rating_history_is_newest_first(monkeypatch) -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        owner = User(slug="viewer", display_name="Viewer")
        older = Movie(tmdb_id=1, title="Older Watch", year=2001, poster_path="/older.jpg")
        newer = Movie(tmdb_id=2, title="Newer Watch", year=2024)
        session.add_all([owner, older, newer])
        session.flush()
        session.add_all(
            [
                UserMovieInteraction(
                    user_id=owner.id,
                    movie_id=older.id,
                    rating=5.0,
                    watched=True,
                    watched_date=date(2024, 1, 1),
                    source="letterboxd",
                ),
                UserMovieInteraction(
                    user_id=owner.id,
                    movie_id=newer.id,
                    rating=3.5,
                    review_text="Recent review",
                    watched=True,
                    watched_date=date(2026, 8, 1),
                    source="letterboxd",
                ),
            ]
        )
        session.commit()

    main_module = import_module("app.main")
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    response = TestClient(app).get("/profiles/viewer/ratings")

    assert response.status_code == 200
    payload = response.json()
    assert [item["title"] for item in payload["ratings"]] == ["Newer Watch", "Older Watch"]
    assert payload["ratings"][0]["review_text"] == "Recent review"
    assert payload["ratings"][1]["poster_url"].endswith("/older.jpg")


def test_profile_export_is_rating_only_and_reimportable(monkeypatch) -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        owner = User(slug="traveler", display_name="Traveling Viewer")
        session.add(owner)
        session.flush()
        session.add_all(
            [
                ImportMapping(
                    user_id=owner.id,
                    source="letterboxd",
                    source_key="https://letterboxd.com/film/alien/",
                    title="Alien",
                    year=1979,
                    status="matched_local",
                    rating=4.5,
                    review_text="Claustrophobic and beautifully designed.",
                    watched=True,
                    rewatch_count=2,
                    watchlisted=False,
                ),
                ImportMapping(
                    user_id=owner.id,
                    source="letterboxd",
                    source_key="watchlist-only",
                    title="Unrated",
                    year=2024,
                    status="pending",
                    rating=None,
                    watched=False,
                    rewatch_count=0,
                    watchlisted=True,
                ),
            ]
        )
        session.commit()

    main_module = import_module("app.main")
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    response = TestClient(app).get("/profiles/traveler/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        manifest = json.loads(bundle.read("movie-compass-profile.json"))
        assert manifest["display_name"] == "Traveling Viewer"
        assert manifest["rated_films"] == 1
        assert bundle.read("ratings.csv").decode("utf-8-sig").count("Alien") == 1
        assert b"Unrated" not in bundle.read("ratings.csv")
        assert bundle.read("diary.csv").decode("utf-8-sig").count("Alien") == 2

    archive = io.BytesIO(response.content)
    with zipfile.ZipFile(archive) as bundle:
        assert {"ratings.csv", "watched.csv", "reviews.csv", "diary.csv"}.issubset(
            bundle.namelist()
        )


def test_movie_compass_backup_restores_exact_tmdb_mapping_and_name(tmp_path: Path) -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        source = User(slug="source", display_name="Careful Critic")
        session.add(source)
        session.flush()
        movie = Movie(tmdb_id=348, title="Alien", original_title="Alien", year=1979)
        session.add(movie)
        session.flush()
        session.add(
            ImportMapping(
                user_id=source.id,
                source="letterboxd",
                source_key="alien:1979",
                movie_id=movie.id,
                title="Alien",
                year=1979,
                status="matched_local",
                rating=4.5,
                watched=True,
                rewatch_count=0,
                watchlisted=False,
            )
        )
        session.commit()
        content, _, _ = build_profile_archive(session, "source")

    archive = tmp_path / "profile.zip"
    archive.write_bytes(content)
    with session_factory() as session:
        destination = User(slug="destination", display_name="Destination")
        session.add(destination)
        session.flush()
        session.add(
            ImportMapping(
                user_id=destination.id,
                source="letterboxd",
                source_key="alien:1979",
                title="Alien",
                year=1979,
                status="pending",
                rating=4.5,
                watched=True,
                rewatch_count=0,
                watchlisted=False,
            )
        )
        session.commit()
        restored = restore_profile_archive(session, archive, "destination")
        mapping = session.scalar(
            select(ImportMapping).where(ImportMapping.user_id == destination.id)
        )
        session.refresh(destination)

    assert restored == 1
    assert mapping.status == "matched_manual"
    assert mapping.movie_id is not None
    assert destination.display_name == "Careful Critic"


def test_movie_compass_backup_round_trips_tv_miniseries_namespace(tmp_path: Path) -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        source = User(slug="tv-source", display_name="TV Source")
        session.add(source)
        session.flush()
        show = Movie(
            tmdb_id=-61617,
            title="Over the Garden Wall",
            original_title="Over the Garden Wall",
            year=2014,
        )
        session.add(show)
        session.flush()
        session.add(
            ImportMapping(
                user_id=source.id,
                source="manual",
                source_key="tmdb:tv:61617",
                movie_id=show.id,
                title=show.title,
                year=show.year,
                status="matched_manual",
                rating=5.0,
                watched=True,
                rewatch_count=0,
                watchlisted=False,
            )
        )
        session.commit()
        content, _, _ = build_profile_archive(session, source.slug)

    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        manifest = json.loads(bundle.read("movie-compass-profile.json"))
        assert manifest["movies"][0]["tmdb_id"] == 61617
        assert manifest["movies"][0]["media_type"] == "tv"

    archive = tmp_path / "tv-profile.zip"
    archive.write_bytes(content)
    with session_factory() as session:
        destination = User(slug="tv-destination", display_name="Destination")
        session.add(destination)
        session.flush()
        mapping = ImportMapping(
            user_id=destination.id,
            source="manual",
            source_key="tmdb:tv:61617",
            title="Over the Garden Wall",
            year=2014,
            status="pending",
            rating=5.0,
            watched=True,
            rewatch_count=0,
            watchlisted=False,
        )
        session.add(mapping)
        session.commit()
        restored = restore_profile_archive(session, archive, destination.slug)
        session.refresh(mapping)
        restored_movie = session.get(Movie, mapping.movie_id)

    assert restored == 1
    assert restored_movie.tmdb_id == -61617
