from importlib import import_module


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
    monkeypatch.setattr(
        main,
        "load_or_fetch_details",
        lambda _client, _ids, _path: ({348: {}, 123: {}}, 2),
    )

    assert main._tmdb_search_ids("Alien", 1979, 10) == [348, 123]
