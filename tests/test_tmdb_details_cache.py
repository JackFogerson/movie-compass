import json
from pathlib import Path

from ingestion.tmdb.client import TmdbNotFound
from ingestion.tmdb.details_cache import load_or_fetch_details


class MissingDetailsClient:
    def movie_details(self, tmdb_id: int, append_to_response: str | None = None) -> dict:
        raise TmdbNotFound(f"missing {tmdb_id}")


def test_missing_tmdb_record_is_cached_and_skipped(tmp_path: Path) -> None:
    cache = tmp_path / "details.json"
    details, fetched = load_or_fetch_details(MissingDetailsClient(), {123}, cache)
    again, fetched_again = load_or_fetch_details(MissingDetailsClient(), {123}, cache)

    assert details == {}
    assert fetched == 1
    assert again == {}
    assert fetched_again == 0


def test_existing_details_without_release_dates_are_refreshed(tmp_path: Path) -> None:
    class CertificationClient:
        def movie_details(self, tmdb_id: int, append_to_response: str | None = None) -> dict:
            assert append_to_response == "credits,keywords,release_dates"
            return {
                "id": tmdb_id,
                "credits": {},
                "keywords": {},
                "release_dates": {"results": []},
            }

    cache = tmp_path / "details.json"
    cache.write_text(
        json.dumps({"42": {"id": 42, "credits": {}, "keywords": {}}}),
        encoding="utf-8",
    )

    details, fetched = load_or_fetch_details(CertificationClient(), {42}, cache)

    assert fetched == 1
    assert details[42]["release_dates"] == {"results": []}


def test_tv_catalog_id_loads_and_normalizes_tv_details(tmp_path: Path) -> None:
    class TvClient:
        def tv_details(self, tmdb_id: int, append_to_response: str | None = None) -> dict:
            assert tmdb_id == 61617
            assert append_to_response == "credits,keywords,content_ratings"
            return {
                "id": tmdb_id,
                "name": "Over the Garden Wall",
                "first_air_date": "2014-11-03",
                "type": "Miniseries",
                "number_of_episodes": 10,
                "episode_run_time": [11],
                "credits": {},
                "keywords": {"results": []},
                "content_ratings": {"results": []},
            }

    details, fetched = load_or_fetch_details(TvClient(), {-61617}, tmp_path / "details.json")

    assert fetched == 1
    assert details[-61617]["id"] == -61617
    assert details[-61617]["media_type"] == "tv"
    assert details[-61617]["runtime"] == 110
