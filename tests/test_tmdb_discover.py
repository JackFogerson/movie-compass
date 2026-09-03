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
