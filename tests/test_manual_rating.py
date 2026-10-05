from datetime import date
from importlib import import_module

from app.db.models import ImportMapping, Movie, User, UserMovieInteraction
from app.main import (
    ManualRatingRequest,
    delete_profile_rating,
    save_manual_rating,
    settings,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def test_manual_rating_is_saved_and_rebuilds_profile(tmp_path, monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        User.__table__,
        Movie.__table__,
        UserMovieInteraction.__table__,
        ImportMapping.__table__,
    ):
        table.create(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.add(User(slug="critic", display_name="Critic"))
        session.commit()

    class FakeTmdbClient:
        def __init__(self, _key):
            pass

        def movie_details(self, tmdb_id, _append):
            assert tmdb_id == 603
            return {
                "id": 603,
                "title": "The Matrix",
                "original_title": "The Matrix",
                "release_date": "1999-03-30",
                "overview": "A simulated reality is exposed.",
                "runtime": 136,
                "poster_path": "/poster.jpg",
                "keywords": {"keywords": []},
                "credits": {"crew": [], "cast": []},
            }

        def search_movie(self, query, year, *, include_adult=False):
            assert (query, year) == ("The Matrix", 1999)
            assert include_adult is True
            return [
                {
                    "id": 603,
                    "title": "The Matrix",
                    "release_date": "1999-03-30",
                    "poster_path": "/poster.jpg",
                }
            ]

        def search_tv(self, _query, _year, *, include_adult=False):
            assert include_adult is True
            return []

        def close(self):
            pass

    main_module = import_module("app.main")
    old_data_dir = settings.data_dir
    settings.data_dir = tmp_path / "data"
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr(main_module, "TmdbClient", FakeTmdbClient)
    monkeypatch.setattr(main_module, "refresh_review_policy", lambda *_args: {"enabled": False})
    monkeypatch.setattr(main_module, "clear_group_recommendation_cache", lambda: None)
    monkeypatch.setattr(main_module, "_latest_artifact", lambda _path: tmp_path / "artifact")
    rebuilt = []
    monkeypatch.setattr(
        main_module,
        "generate_recommendations",
        lambda *_args, **_kwargs: rebuilt.append(True),
    )
    try:
        result = save_manual_rating(
            "critic",
            ManualRatingRequest(
                tmdb_id=603,
                title="The Matrix",
                year=1999,
                rating=4.5,
                review_text="Still exhilarating.",
            ),
        )
        search = main_module.rating_movie_search("The Matrix", 1999, "critic")
        class OfflineTmdbClient:
            def __init__(self, _key):
                pass

            def movie_details(self, _tmdb_id, _append):
                from concurrent.futures import Future

                from tenacity import RetryError

                attempt = Future()
                attempt.set_exception(OSError("offline"))
                raise RetryError(attempt)

            def search_movie(self, _query, _year, *, include_adult=False):
                raise AssertionError("Offline cached save should not search")

            def search_tv(self, _query, _year, *, include_adult=False):
                raise AssertionError("Offline cached save should not search")

            def close(self):
                pass

        monkeypatch.setattr(main_module, "TmdbClient", OfflineTmdbClient)
        offline_result = save_manual_rating(
            "critic",
            ManualRatingRequest(
                tmdb_id=603,
                title="The Matrix",
                year=1999,
                rating=4.5,
                review_text="Still exhilarating.",
            ),
        )
    finally:
        settings.data_dir = old_data_dir

    assert result["ranking_updated"] is True
    assert search["results"][0]["current_rating"] == 4.5
    assert search["results"][0]["current_review_text"] == "Still exhilarating."
    assert "bundled movie details" in offline_result["details_warning"]
    assert rebuilt == [True, True]
    with session_factory() as session:
        interaction = session.scalar(select(UserMovieInteraction))
        mapping = session.scalar(select(ImportMapping))
        assert float(interaction.rating) == 4.5
        assert interaction.review_text == "Still exhilarating."
        assert interaction.watched_date == date.today()
        assert mapping.watched_date == date.today()
        assert mapping.status == "matched_manual"


def test_tv_miniseries_can_be_found_and_saved_as_a_rating(tmp_path, monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        User.__table__,
        Movie.__table__,
        UserMovieInteraction.__table__,
        ImportMapping.__table__,
    ):
        table.create(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.add(User(slug="miniseries-fan", display_name="Miniseries Fan"))
        session.commit()

    tv_search = {
        "id": 61617,
        "name": "Over the Garden Wall",
        "original_name": "Over the Garden Wall",
        "first_air_date": "2014-11-03",
        "poster_path": "/garden.jpg",
    }

    class FakeTmdbClient:
        def __init__(self, _key):
            pass

        def search_movie(self, _query, _year, *, include_adult=False):
            assert include_adult is True
            return []

        def search_tv(self, query, year, *, include_adult=False):
            assert (query, year, include_adult) == ("Over the Garden Wall", 2014, True)
            return [tv_search]

        def tv_details(self, tmdb_id, _append):
            assert tmdb_id == 61617
            return {
                **tv_search,
                "type": "Miniseries",
                "number_of_episodes": 10,
                "episode_run_time": [11],
                "overview": "Two brothers become lost in the Unknown.",
                "genres": [{"name": "Animation"}, {"name": "Mystery"}],
                "keywords": {"results": [{"name": "dark fantasy"}]},
                "credits": {"crew": [], "cast": [{"name": "Elijah Wood"}]},
                "content_ratings": {
                    "results": [{"iso_3166_1": "US", "rating": "TV-PG"}]
                },
            }

        def close(self):
            pass

    main_module = import_module("app.main")
    old_data_dir = settings.data_dir
    settings.data_dir = tmp_path / "data"
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr(main_module, "TmdbClient", FakeTmdbClient)
    monkeypatch.setattr(main_module, "refresh_review_policy", lambda *_args: {"enabled": False})
    monkeypatch.setattr(main_module, "clear_group_recommendation_cache", lambda: None)
    monkeypatch.setattr(main_module, "_latest_artifact", lambda _path: tmp_path / "artifact")
    monkeypatch.setattr(main_module, "generate_recommendations", lambda *_args, **_kwargs: {})
    try:
        search = main_module.rating_movie_search(
            "Over the Garden Wall", 2014, "miniseries-fan"
        )
        selected = search["results"][0]
        result = save_manual_rating(
            "miniseries-fan",
            ManualRatingRequest(
                tmdb_id=selected["tmdb_id"],
                title=selected["title"],
                year=selected["year"],
                rating=5.0,
                review_text="A perfect autumn miniseries.",
            ),
        )
    finally:
        settings.data_dir = old_data_dir

    assert selected == {
        "tmdb_id": -61617,
        "title": "Over the Garden Wall",
        "year": 2014,
        "poster_url": "https://image.tmdb.org/t/p/w185/garden.jpg",
        "media_type": "tv",
        "adult": False,
        "current_rating": None,
        "current_review_text": None,
    }
    assert result["media_type"] == "tv"
    with session_factory() as session:
        movie = session.scalar(select(Movie))
        interaction = session.scalar(select(UserMovieInteraction))
        mapping = session.scalar(select(ImportMapping))
        assert movie.tmdb_id == -61617
        assert movie.runtime == 110
        assert float(interaction.rating) == 5.0
        assert mapping.source_key == "tmdb:tv:61617"


def test_specific_rating_can_be_deleted_and_profile_rebuilt(tmp_path, monkeypatch) -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    for table in (
        User.__table__,
        Movie.__table__,
        UserMovieInteraction.__table__,
        ImportMapping.__table__,
    ):
        table.create(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        owner = User(slug="critic", display_name="Critic")
        movie = Movie(tmdb_id=603, title="Wrong Matrix", year=1999)
        session.add_all([owner, movie])
        session.flush()
        session.add(
            UserMovieInteraction(
                user_id=owner.id,
                movie_id=movie.id,
                rating=4.5,
                watched=True,
                source="manual",
            )
        )
        session.add(
            ImportMapping(
                user_id=owner.id,
                source="manual",
                source_key="tmdb:movie:603",
                title=movie.title,
                year=movie.year,
                movie_id=movie.id,
                status="matched_manual",
                rating=4.5,
                watched=True,
            )
        )
        session.commit()
        movie_id = movie.id

    main_module = import_module("app.main")
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr(main_module, "refresh_review_policy", lambda *_args: {})
    monkeypatch.setattr(main_module, "clear_group_recommendation_cache", lambda: None)
    monkeypatch.setattr(main_module, "_latest_artifact", lambda _path: tmp_path / "artifact")
    rebuilt = []
    monkeypatch.setattr(
        main_module,
        "generate_recommendations",
        lambda *_args, **_kwargs: rebuilt.append(True),
    )

    result = delete_profile_rating("critic", movie_id)

    assert result["deleted"] is True
    assert result["title"] == "Wrong Matrix"
    assert result["ranking_updated"] is True
    assert rebuilt == [True]
    with session_factory() as session:
        assert session.scalar(select(UserMovieInteraction)) is None
        assert session.scalar(select(ImportMapping)) is None
        assert session.scalar(select(Movie)).title == "Wrong Matrix"
