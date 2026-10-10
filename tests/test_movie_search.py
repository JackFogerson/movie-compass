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

        def search_movie(self, query, year, *, include_adult=False):
            assert (query, year) == ("Alien", 1979)
            assert include_adult is True
            return [{"id": 348}, {"id": 999}, {"id": 123}]

        def search_tv(self, _query, _year, *, include_adult=False):
            assert include_adult is True
            return []

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

        def search_movie(self, _query, _year, *, include_adult=False):
            assert include_adult is True
            from concurrent.futures import Future

            from tenacity import RetryError

            attempt = Future()
            attempt.set_exception(OSError("offline"))
            raise RetryError(attempt)

        def search_tv(self, _query, _year, *, include_adult=False):
            assert include_adult is True
            return []

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

        def search_movie(self, _query, _year, *, include_adult=False):
            assert include_adult is True
            from concurrent.futures import Future

            from tenacity import RetryError

            attempt = Future()
            attempt.set_exception(OSError("offline"))
            raise RetryError(attempt)

        def search_tv(self, _query, _year, *, include_adult=False):
            assert include_adult is True
            return []

        def close(self):
            pass

    monkeypatch.setattr(main, "TmdbClient", FakeClient)

    with pytest.raises(HTTPException) as error:
        main._tmdb_search_ids("Leviticus", 2026, 10)
    assert error.value.status_code == 503
    assert "temporarily unreachable" in error.value.detail


def test_actor_filter_expands_exact_person_movie_credits(monkeypatch) -> None:
    main = import_module("app.main")
    monkeypatch.setattr(main.settings, "tmdb_api_key", "test-key")

    class FakeClient:
        def __init__(self, _key):
            pass

        def search_person(self, name, *, include_adult=False):
            assert name == "Anna Kendrick"
            assert include_adult is False
            return [
                {"id": 99, "name": "Anna Kendrick", "popularity": 20},
                {"id": 98, "name": "Anna Kendrick Tribute", "popularity": 100},
            ]

        def person_combined_credits(self, person_id):
            assert person_id == 99
            return {
                "cast": [
                    {"id": 10, "media_type": "movie", "popularity": 3},
                    {"id": 20, "media_type": "movie", "popularity": 8},
                    {"id": 30, "media_type": "tv", "popularity": 12},
                    {"id": 40, "media_type": "movie", "popularity": 20, "adult": True},
                ]
            }

        def close(self):
            pass

    monkeypatch.setattr(main, "TmdbClient", FakeClient)
    monkeypatch.setattr(
        main,
        "load_or_fetch_details",
        lambda _client, ids, _path: ({value: {} for value in ids}, len(ids)),
    )

    assert main._person_filter_candidate_ids("actors", "Anna Kendrick", "movie") == [
        20,
        10,
    ]


def test_theme_filter_discovers_tmdb_keyword_titles(monkeypatch) -> None:
    main = import_module("app.main")
    monkeypatch.setattr(main.settings, "tmdb_api_key", "test-key")

    class FakeClient:
        def __init__(self, _key):
            pass

        def search_keyword(self, query):
            assert query == "Halloween"
            return [
                {"id": 1, "name": "Halloween party"},
                {"id": 2, "name": "Halloween"},
            ]

        def discover_by_keyword(self, keyword_id, media_type, page=1):
            assert keyword_id == 2
            assert media_type == "movie"
            return {"results": [{"id": 20}, {"id": 10}], "total_pages": 1}

        def close(self):
            pass

    monkeypatch.setattr(main, "TmdbClient", FakeClient)
    monkeypatch.setattr(
        main,
        "load_or_fetch_details",
        lambda _client, ids, _path: ({value: {} for value in ids}, len(ids)),
    )

    assert main._theme_filter_candidate_ids("Halloween", "movie") == [20, 10]


def test_company_filter_discovers_related_tmdb_company_titles(monkeypatch) -> None:
    main = import_module("app.main")
    monkeypatch.setattr(main.settings, "tmdb_api_key", "test-key")

    class FakeClient:
        def __init__(self, _key):
            pass

        def search_company(self, query):
            assert query == "Lionsgate"
            return [
                {"id": 1, "name": "Lionsgate"},
                {"id": 2, "name": "Lionsgate UK"},
                {"id": 3, "name": "Unrelated Studio"},
            ]

        def discover_by_company(self, company_id, media_type, page=1):
            assert media_type == "movie"
            rows = {1: [{"id": 20}], 2: [{"id": 10}]}
            return {"results": rows[company_id], "total_pages": 1}

        def close(self):
            pass

    monkeypatch.setattr(main, "TmdbClient", FakeClient)
    monkeypatch.setattr(
        main,
        "load_or_fetch_details",
        lambda _client, ids, _path: ({value: {} for value in ids}, len(ids)),
    )

    assert main._company_filter_candidate_ids("Lionsgate", "movie") == [20, 10]


def test_combined_filter_discovery_scans_every_tmdb_page(monkeypatch) -> None:
    main = import_module("app.main")
    monkeypatch.setattr(main.settings, "tmdb_api_key", "test-key")
    captured_rows = []

    class FakeClient:
        def __init__(self, _key):
            pass

        def search_company(self, query):
            assert query == "Lionsgate"
            return [{"id": 1, "name": "Lionsgate"}]

        def discover_filtered(self, media_type, *, page, filters):
            assert media_type == "movie"
            assert filters["with_companies"] == "1"
            assert filters["with_genres"] == 35
            assert filters["primary_release_date.gte"] == "2000-01-01"
            return {
                "results": [
                    {
                        "id": page,
                        "title": f"Film {page}",
                        "release_date": "2001-01-01",
                        "genre_ids": [35],
                    }
                ],
                "total_pages": 3,
                "total_results": 3,
            }

        def close(self):
            pass

    monkeypatch.setattr(main, "TmdbClient", FakeClient)
    monkeypatch.setattr(
        main,
        "merge_discovery_results",
        lambda _path, rows: captured_rows.extend(rows),
    )

    ids, coverage = main._discover_filtered_candidate_ids(
        [{"category": "companies", "value": "Lionsgate"}],
        None,
        "movie",
        year_min=2000,
        genre="Comedy",
    )

    assert ids == [1, 2, 3]
    assert coverage == {
        "mode": "tmdb_discover",
        "matches_reported": 3,
        "matches_retrieved": 3,
        "pages_scanned": 3,
        "page_cap": main.DISCOVERY_MAX_PAGES,
        "truncated": False,
    }
    assert len(captured_rows) == 3
    assert captured_rows[0]["production_companies"] == [{"id": 1, "name": "Lionsgate"}]


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


def test_manual_rating_search_uses_cached_result_during_tmdb_outage(monkeypatch) -> None:
    main = import_module("app.main")
    monkeypatch.setattr(main.settings, "tmdb_api_key", "test-key")
    monkeypatch.setattr(
        main,
        "_local_movie_search_results",
        lambda *_args: [
            {
                "id": 1058424,
                "title": "Hope",
                "release_date": "2026-07-15",
                "poster_path": "/hope.jpg",
            }
        ],
    )

    class OfflineClient:
        def __init__(self, _key):
            pass

        def search_movie(self, _query, _year, *, include_adult=False):
            assert include_adult is True
            from concurrent.futures import Future

            from tenacity import RetryError

            attempt = Future()
            attempt.set_exception(OSError("offline"))
            raise RetryError(attempt)

        def search_tv(self, _query, _year, *, include_adult=False):
            assert include_adult is True
            return []

        def close(self):
            pass

    monkeypatch.setattr(main, "TmdbClient", OfflineClient)

    result = main.rating_movie_search("hope", 2026, None)

    assert result["results"] == [
        {
            "tmdb_id": 1058424,
            "title": "Hope",
            "year": 2026,
            "poster_url": "https://image.tmdb.org/t/p/w185/hope.jpg",
            "media_type": "movie",
            "adult": False,
        }
    ]
    assert "bundled catalog" in result["warning"]
