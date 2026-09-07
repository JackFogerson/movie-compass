import gzip
import json
from importlib import import_module
from pathlib import Path

import pytest
from fastapi import HTTPException


def test_tmdb_score_search_preserves_relevance_order(monkeypatch) -> None:
    main = import_module("app.main")
    monkeypatch.setattr(main.settings, "tmdb_api_key", "test-key")

    class FakeClient:
        def __init__(self, _key):
            pass

        def search_movie(self, query, year):
            assert (query, year) == ("Alien", 1979)
            return [{"id": 348}, {"id": 999}, {"id": 123}]

        def close(self):
            pass

    monkeypatch.setattr(main, "TmdbClient", FakeClient)
    monkeypatch.setattr(main, "_local_movie_search_ids", lambda *_args: [])
    monkeypatch.setattr(
        main,
        "load_or_fetch_details",
        lambda _client, _ids, _path: ({348: {}, 123: {}}, 2),
    )

    assert main._tmdb_search_ids("Alien", 1979, 10) == [348, 123]


def test_tmdb_score_search_falls_back_to_local_catalog_after_retry_error(monkeypatch) -> None:
    main = import_module("app.main")
    monkeypatch.setattr(main.settings, "tmdb_api_key", "test-key")
    monkeypatch.setattr(main, "_local_movie_search_ids", lambda *_args: [374720])

    class FakeClient:
        def __init__(self, _key):
            pass

        def search_movie(self, _query, _year):
            from concurrent.futures import Future

            from tenacity import RetryError

            attempt = Future()
            attempt.set_exception(OSError("offline"))
            raise RetryError(attempt)

        def close(self):
            pass

    monkeypatch.setattr(main, "TmdbClient", FakeClient)

    assert main._tmdb_search_ids("Dunkirk", 2017, 10) == [374720]


def test_tmdb_score_search_reports_outage_instead_of_false_no_match(monkeypatch) -> None:
    main = import_module("app.main")
    monkeypatch.setattr(main.settings, "tmdb_api_key", "test-key")
    monkeypatch.setattr(main, "_local_movie_search_ids", lambda *_args: [])

    class FakeClient:
        def __init__(self, _key):
            pass

        def search_movie(self, _query, _year):
            from concurrent.futures import Future

            from tenacity import RetryError

            attempt = Future()
            attempt.set_exception(OSError("offline"))
            raise RetryError(attempt)

        def close(self):
            pass

    monkeypatch.setattr(main, "TmdbClient", FakeClient)

    with pytest.raises(HTTPException) as error:
        main._tmdb_search_ids("Leviticus", 2026, 10)
    assert error.value.status_code == 503
    assert "temporarily unreachable" in error.value.detail


def test_local_search_includes_cached_tmdb_only_titles(tmp_path: Path, monkeypatch) -> None:
    main = import_module("app.main")
    artifact = tmp_path / "artifacts" / "movielens-32m-test"
    artifact.mkdir(parents=True)
    (artifact / "manifest.json").write_text(
        json.dumps({"files": {"catalog": "catalog.csv.gz"}}), encoding="utf-8"
    )
    with gzip.open(artifact / "catalog.csv.gz", "wt", encoding="utf-8") as handle:
        handle.write("movieId,clean_title,year,tmdb_id\n1,Older Film,2000,10\n")
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    (processed / "tmdb-rich-details.json").write_text(
        json.dumps(
            {
                "1564614": {
                    "id": 1564614,
                    "title": "Leviticus",
                    "release_date": "2026-06-17",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(main.settings, "ml_artifacts_dir", tmp_path / "artifacts")
    monkeypatch.setattr(main.settings, "data_dir", tmp_path / "data")

    assert main._local_movie_search_ids("Leviticus", 2026, 10) == [1564614]
