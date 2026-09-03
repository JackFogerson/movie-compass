import csv
import io
import zipfile
from pathlib import Path

from app.db.base import Base
from app.db.models import (
    ImportMapping,
    ImportRun,
    MappingDecision,
    Movie,
    TmdbSearchCache,
    User,
    UserMovieInteraction,
)
from app.services.letterboxd_import import import_letterboxd_archive
from app.services.tmdb_mapping import map_pending_letterboxd, resolve_letterboxd_links
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


class FakeTmdbClient:
    def __init__(self) -> None:
        self.calls = 0

    def search_movie(self, title: str, year: int | None = None) -> list[dict]:
        self.calls += 1
        return [{"id": 329865, "title": title, "release_date": f"{year}-11-10"}]


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
            ImportRun.__table__,
            TmdbSearchCache.__table__,
            MappingDecision.__table__,
        ],
    )
    return Session(engine)


def _archive(path: Path) -> Path:
    output = io.StringIO()
    fields = ["Date", "Name", "Year", "Letterboxd URI", "Rating"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerow(
        {
            "Date": "2024-01-01",
            "Name": "Arrival",
            "Year": "2016",
            "Letterboxd URI": "https://boxd.it/ed3g",
            "Rating": "4.5",
        }
    )
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("export/ratings.csv", output.getvalue())
    return path


def test_import_is_idempotent_by_archive_and_source_key(tmp_path: Path) -> None:
    session = _session()
    archive = _archive(tmp_path / "letterboxd.zip")
    first = import_letterboxd_archive(session, archive)
    second = import_letterboxd_archive(session, archive)
    assert first.created == 1
    assert second.already_imported is True
    assert session.scalar(select(func.count()).select_from(ImportRun)) == 1
    assert session.scalar(select(func.count()).select_from(ImportMapping)) == 1


def test_force_reprocesses_a_completed_archive(tmp_path: Path) -> None:
    session = _session()
    archive = _archive(tmp_path / "letterboxd.zip")
    import_letterboxd_archive(session, archive)
    forced = import_letterboxd_archive(session, archive, force=True)
    assert forced.already_imported is False
    assert forced.updated == 1


def test_mapping_creates_interaction_and_reuses_cache_across_users(tmp_path: Path) -> None:
    session = _session()
    archive = _archive(tmp_path / "letterboxd.zip")
    first = import_letterboxd_archive(session, archive, "one")
    second = import_letterboxd_archive(session, archive, "two")
    client = FakeTmdbClient()
    first_result = map_pending_letterboxd(session, client, first.user_id)
    second_result = map_pending_letterboxd(session, client, second.user_id)
    assert first_result.matched == 1
    assert second_result.cache_hits == 1
    assert client.calls == 1
    assert session.scalar(select(func.count()).select_from(Movie)) == 1
    assert session.scalar(select(func.count()).select_from(UserMovieInteraction)) == 2
    ratings = session.scalars(select(UserMovieInteraction.rating)).all()
    assert ratings == [4.5, 4.5]


def test_import_ignores_watchlist_only_films(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "letterboxd.zip")
    watchlist = io.StringIO()
    writer = csv.DictWriter(
        watchlist,
        fieldnames=["Date", "Name", "Year", "Letterboxd URI"],
    )
    writer.writeheader()
    writer.writerow(
        {
            "Date": "2024-01-02",
            "Name": "Unrated Watchlist Movie",
            "Year": "2020",
            "Letterboxd URI": "https://boxd.it/watchlist-only",
        }
    )
    with zipfile.ZipFile(archive, "a") as bundle:
        bundle.writestr("export/watchlist.csv", watchlist.getvalue())

    session = _session()
    result = import_letterboxd_archive(session, archive, "rated-only")

    assert result.movies_staged == 1
    mappings = session.scalars(select(ImportMapping)).all()
    assert [mapping.title for mapping in mappings] == ["Arrival"]


def test_letterboxd_link_resolves_ambiguous_title_without_api_details(tmp_path: Path) -> None:
    class ExactLinkClient(FakeTmdbClient):
        def letterboxd_tmdb_id(self, source_url: str) -> int:
            assert source_url == "https://boxd.it/ed3g"
            return 1684326

        def movie_details(self, _tmdb_id: int) -> dict:
            raise RuntimeError("new record is not available from the API yet")

    session = _session()
    imported = import_letterboxd_archive(session, _archive(tmp_path / "letterboxd.zip"))
    mapping = session.scalar(select(ImportMapping))
    mapping.status = "ambiguous"
    session.commit()

    result = resolve_letterboxd_links(session, ExactLinkClient(), imported.user_id)

    assert result.matched == 1
    assert mapping.status == "matched"
    assert mapping.movie_id is not None
    movie = session.get(Movie, mapping.movie_id)
    assert movie.tmdb_id == 1684326
