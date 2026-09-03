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
