import httpx

from ingestion.tmdb.client import TmdbClient, match_movie


def test_connection_check_uses_authenticated_configuration_endpoint() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"images": {}})

    client = TmdbClient("test-key", transport=httpx.MockTransport(handler))
    try:
        client.check_connection()
    finally:
        client.close()

    assert seen[0].url.path == "/3/configuration"
    assert seen[0].url.params["api_key"] == "test-key"


def test_exact_title_and_year_is_matched() -> None:
    result = match_movie(
        "Arrival", 2016, [{"id": 329865, "title": "Arrival", "release_date": "2016-11-10"}]
    )
    assert result.status == "matched"
    assert result.candidate and result.candidate.tmdb_id == 329865


def test_close_candidates_are_ambiguous() -> None:
    result = match_movie(
        "The Thing",
        1982,
        [
            {"id": 1, "title": "The Thing", "release_date": "1982-01-01"},
            {"id": 2, "title": "The Thing", "release_date": "1982-06-01"},
        ],
    )
    assert result.status == "ambiguous"
    assert result.candidate is None


def test_weak_candidate_is_unresolved() -> None:
    result = match_movie(
        "Arrival", 2016, [{"id": 99, "title": "Unrelated", "release_date": "1970-01-01"}]
    )
    assert result.status == "unresolved"


def test_exact_title_with_one_year_release_difference_is_matched() -> None:
    result = match_movie(
        "Perfect Blue",
        1997,
        [{"id": 10494, "title": "Perfect Blue", "release_date": "1998-02-28"}],
    )
    assert result.status == "matched"
    assert result.candidate and result.candidate.confidence == 0.91


def test_year_tolerance_does_not_override_duplicate_candidates() -> None:
    result = match_movie(
        "Example",
        2025,
        [
            {"id": 1, "title": "Example", "release_date": "2026-01-01"},
            {"id": 2, "title": "Example", "release_date": "2026-02-01"},
        ],
    )
    assert result.status == "ambiguous"
