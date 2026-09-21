import httpx

from ingestion.tmdb.client import TmdbClient


def test_discover_uses_primary_release_window() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["primary_release_date.gte"] == "2024-01-01"
        assert request.url.params["primary_release_date.lte"] == "2026-12-31"
        assert "release_date.gte" not in request.url.params
        return httpx.Response(200, json={"page": 1, "total_pages": 1, "results": []})

    client = TmdbClient("test-key", transport=httpx.MockTransport(handler))
    try:
        result = client.discover_movies(
            release_date_gte="2024-01-01",
            release_date_lte="2026-12-31",
        )
    finally:
        client.close()

    assert result["results"] == []


def test_direct_movie_search_can_include_adult_titles() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/search/movie")
        assert request.url.params["query"] == "Through the Looking Glass"
        assert request.url.params["year"] == "1976"
        assert request.url.params["include_adult"] == "true"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 119488,
                        "title": "Through the Looking Glass",
                        "release_date": "1976-09-22",
                    }
                ]
            },
        )

    client = TmdbClient("test-key", transport=httpx.MockTransport(handler))
    try:
        results = client.search_movie(
            "Through the Looking Glass", 1976, include_adult=True
        )
    finally:
        client.close()

    assert results[0]["id"] == 119488
