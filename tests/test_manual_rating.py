from importlib import import_module

from app.db.models import ImportMapping, Movie, User, UserMovieInteraction
from app.main import ManualRatingRequest, save_manual_rating, settings
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
    finally:
        settings.data_dir = old_data_dir

    assert result["ranking_updated"] is True
    assert rebuilt == [True]
    with session_factory() as session:
        interaction = session.scalar(select(UserMovieInteraction))
        mapping = session.scalar(select(ImportMapping))
        assert float(interaction.rating) == 4.5
        assert interaction.review_text == "Still exhilarating."
        assert mapping.status == "matched_manual"
