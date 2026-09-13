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
