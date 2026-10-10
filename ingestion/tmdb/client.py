from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ingestion.letterboxd.parser import normalize_title


class TmdbError(RuntimeError):
    pass


class TmdbNotFound(TmdbError):
    pass


def tv_catalog_id(tmdb_id: int) -> int:
    """Namespace TMDB TV IDs away from movie IDs without changing database schemas."""
    return -abs(int(tmdb_id))


def is_tv_catalog_id(tmdb_id: int) -> bool:
    return int(tmdb_id) < 0


def normalize_tv_search_result(value: dict) -> dict:
    """Present a TMDB TV search row in the movie-shaped ranking interface."""
    result = dict(value)
    result.update(
        {
            "id": tv_catalog_id(int(value["id"])),
            "tmdb_external_id": int(value["id"]),
            "media_type": "tv",
            "title": value.get("name") or value.get("original_name") or "Untitled",
            "original_title": value.get("original_name") or value.get("name"),
            "release_date": value.get("first_air_date") or "",
        }
    )
    return result


def rank_title_search_results(query: str, results: list[dict], limit: int = 12) -> list[dict]:
    """Rank title search rows locally and suppress weak matches when full matches exist."""
    query_title = normalize_title(query)
    query_tokens = set(query_title.split())

    def candidate_titles(item: dict) -> list[str]:
        values = [
            item.get("title"),
            item.get("original_title"),
            item.get("name"),
            item.get("original_name"),
        ]
        return list(dict.fromkeys(normalize_title(str(value)) for value in values if value))

    scored: list[tuple[tuple, int, dict]] = []
    for position, item in enumerate(results):
        titles = candidate_titles(item)
        if not titles:
            scored.append(((9, 1.0, position), position, item))
            continue
        best_title = min(
            titles,
            key=lambda title: (
                0 if title == query_title else 1,
                0 if title.startswith(query_title) else 1,
                abs(len(title) - len(query_title)),
            ),
        )
        title_tokens = set(best_title.split())
        overlap = len(query_tokens & title_tokens)
        coverage = overlap / len(query_tokens) if query_tokens else 0.0
        full_match = bool(query_tokens) and query_tokens <= title_tokens
        if best_title == query_title:
            match_class = 0
        elif best_title.startswith(query_title):
            match_class = 1
        elif query_title in best_title:
            match_class = 2
        elif full_match:
            match_class = 3
        else:
            match_class = 4
        popularity = float(item.get("popularity") or 0.0)
        scored.append(
            (
                (
                    match_class,
                    -coverage,
                    abs(len(title_tokens) - len(query_tokens)),
                    -popularity,
                    position,
                ),
                position,
                item,
            )
        )

    # When TMDB found titles containing every meaningful query word, results
    # matching only one word are noise (and can expose unrelated adult art).
    has_full_match = len(query_tokens) > 1 and any(row[0][0] <= 3 for row in scored)
    if has_full_match:
        scored = [row for row in scored if row[0][0] <= 3]
    scored.sort(key=lambda row: row[0])
    return [row[2] for row in scored[:limit]]


def normalize_tv_details(value: dict) -> dict:
    """Normalize TV/miniseries metadata for the existing hybrid content model."""
    result = normalize_tv_search_result(value)
    episode_runtimes = [
        int(runtime)
        for runtime in value.get("episode_run_time") or []
        if str(runtime).isdigit() and int(runtime) > 0
    ]
    episode_runtime = episode_runtimes[0] if episode_runtimes else None
    episode_count = int(value.get("number_of_episodes") or 0)
    is_miniseries = str(value.get("type") or "").casefold() == "miniseries"
    result["runtime"] = (
        episode_runtime * episode_count
        if is_miniseries and episode_runtime and episode_count
        else episode_runtime
    )
    result["runtime_label"] = (
        f"{result['runtime']} min total"
        if is_miniseries and result["runtime"]
        else f"{result['runtime']} min/episode"
        if result["runtime"]
        else None
    )
    keywords = value.get("keywords") or {}
    if "keywords" not in keywords:
        keywords = {"keywords": keywords.get("results") or []}
    result["keywords"] = keywords
    result["release_dates"] = value.get("release_dates") or {}
    result["content_ratings"] = value.get("content_ratings") or {}
    return result


def _check_response(response: httpx.Response, *, resource: str) -> None:
    if response.status_code == 429:
        raise TmdbError("TMDB rate limit exceeded; retry later")
    if response.status_code == 404:
        raise TmdbNotFound(f"TMDB resource not found: {resource}")
    if response.is_error:
        raise TmdbError(f"TMDB request failed with status {response.status_code}: {resource}")


@dataclass(frozen=True)
class MatchCandidate:
    tmdb_id: int
    title: str
    year: int | None
    confidence: float


@dataclass(frozen=True)
class MatchResult:
    status: str
    candidate: MatchCandidate | None
    candidates: tuple[MatchCandidate, ...]


class TmdbClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.themoviedb.org/3",
        transport: httpx.BaseTransport | None = None,
    ):
        if not api_key:
            raise ValueError("TMDB_API_KEY is required for TMDB matching")
        self._client = httpx.Client(
            base_url=base_url,
            params={"api_key": api_key},
            timeout=20,
            transport=transport,
            follow_redirects=True,
        )
        # Public page requests intentionally use a separate client so the TMDB
        # API key is never attached to a Letterboxd URL.
        self._public_client = httpx.Client(
            timeout=20, transport=transport, follow_redirects=True
        )

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def letterboxd_tmdb_id(self, source_url: str) -> int | None:
        """Resolve Letterboxd's own canonical TMDB link for a film page."""
        parsed = urlparse(source_url)
        if parsed.scheme != "https" or parsed.hostname not in {"boxd.it", "letterboxd.com"}:
            return None
        response = self._public_client.get(source_url)
        _check_response(response, resource="Letterboxd film link")
        match = re.search(r"themoviedb\.org/movie/(\d+)", response.text)
        return int(match.group(1)) if match else None

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def search_movie(
        self,
        title: str,
        year: int | None = None,
        *,
        include_adult: bool = False,
    ) -> list[dict]:
        params: dict[str, str | int] = {
            "query": title,
            "include_adult": str(include_adult).lower(),
        }
        if year:
            params["year"] = year
        response = self._client.get("/search/movie", params=params)
        _check_response(response, resource="movie search")
        return response.json().get("results", [])

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def check_connection(self) -> None:
        """Verify both network reachability and the configured TMDB credential."""
        response = self._client.get("/configuration")
        _check_response(response, resource="configuration")

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def movie_details(self, tmdb_id: int, append_to_response: str | None = None) -> dict:
        params = {"append_to_response": append_to_response} if append_to_response else None
        response = self._client.get(f"/movie/{tmdb_id}", params=params)
        _check_response(response, resource=f"movie {tmdb_id}")
        return response.json()

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def search_tv(
        self,
        title: str,
        year: int | None = None,
        *,
        include_adult: bool = False,
    ) -> list[dict]:
        params: dict[str, str | int] = {
            "query": title,
            "include_adult": str(include_adult).lower(),
        }
        if year:
            params["first_air_date_year"] = year
        response = self._client.get("/search/tv", params=params)
        _check_response(response, resource="TV search")
        return response.json().get("results", [])

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def search_person(self, name: str, *, include_adult: bool = False) -> list[dict]:
        response = self._client.get(
            "/search/person",
            params={"query": name, "include_adult": str(include_adult).lower()},
        )
        _check_response(response, resource="person search")
        return response.json().get("results", [])

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def person_combined_credits(self, person_id: int) -> dict:
        response = self._client.get(f"/person/{person_id}/combined_credits")
        _check_response(response, resource=f"person {person_id} credits")
        return response.json()

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def search_keyword(self, query: str) -> list[dict]:
        response = self._client.get("/search/keyword", params={"query": query})
        _check_response(response, resource="keyword search")
        return response.json().get("results", [])

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def discover_by_keyword(self, keyword_id: int, media_type: str, page: int = 1) -> dict:
        resource = "tv" if media_type == "tv" else "movie"
        response = self._client.get(
            f"/discover/{resource}",
            params={
                "include_adult": "false",
                "language": "en-US",
                "page": page,
                "sort_by": "popularity.desc",
                "with_keywords": keyword_id,
            },
        )
        _check_response(response, resource=f"{resource} keyword discovery")
        return response.json()

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def search_company(self, query: str) -> list[dict]:
        response = self._client.get("/search/company", params={"query": query})
        _check_response(response, resource="company search")
        return response.json().get("results", [])

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def discover_by_company(self, company_id: int, media_type: str, page: int = 1) -> dict:
        resource = "tv" if media_type == "tv" else "movie"
        response = self._client.get(
            f"/discover/{resource}",
            params={
                "include_adult": "false",
                "language": "en-US",
                "page": page,
                "sort_by": "popularity.desc",
                "with_companies": company_id,
            },
        )
        _check_response(response, resource=f"{resource} company discovery")
        return response.json()

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def tv_details(self, tmdb_id: int, append_to_response: str | None = None) -> dict:
        params = {"append_to_response": append_to_response} if append_to_response else None
        response = self._client.get(f"/tv/{tmdb_id}", params=params)
        _check_response(response, resource=f"TV series {tmdb_id}")
        return response.json()

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def discover_movies(
        self,
        *,
        release_date_gte: str,
        release_date_lte: str,
        page: int = 1,
        region: str = "US",
        minimum_votes: int = 20,
    ) -> dict:
        response = self._client.get(
            "/discover/movie",
            params={
                "include_adult": "false",
                "include_video": "false",
                "language": "en-US",
                "page": page,
                "region": region,
                "primary_release_date.gte": release_date_gte,
                "primary_release_date.lte": release_date_lte,
                "sort_by": "popularity.desc",
                "vote_count.gte": minimum_votes,
            },
        )
        _check_response(response, resource="movie discovery")
        return response.json()

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def discover_tv(
        self,
        *,
        page: int = 1,
        minimum_votes: int = 20,
        first_air_date_gte: str | None = None,
        first_air_date_lte: str | None = None,
    ) -> dict:
        params: dict[str, str | int] = {
            "include_adult": "false",
            "language": "en-US",
            "page": page,
            "sort_by": "popularity.desc",
            "vote_count.gte": minimum_votes,
        }
        if first_air_date_gte:
            params["first_air_date.gte"] = first_air_date_gte
        if first_air_date_lte:
            params["first_air_date.lte"] = first_air_date_lte
        response = self._client.get("/discover/tv", params=params)
        _check_response(response, resource="TV discovery")
        return response.json()

    def close(self) -> None:
        self._client.close()
        self._public_client.close()


def match_movie(
    title: str,
    year: int | None,
    results: list[dict],
    accept_threshold: float = 0.90,
    ambiguity_margin: float = 0.04,
) -> MatchResult:
    normalized = normalize_title(title)
    candidates: list[MatchCandidate] = []
    for result in results:
        candidate_title = result.get("title") or result.get("original_title") or ""
        release = result.get("release_date") or ""
        candidate_year = int(release[:4]) if len(release) >= 4 and release[:4].isdigit() else None
        title_score = SequenceMatcher(None, normalized, normalize_title(candidate_title)).ratio()
        year_score = 0.0
        if year is None or candidate_year is None:
            year_score = 0.5
        elif candidate_year == year:
            year_score = 1.0
        elif abs(candidate_year - year) == 1:
            year_score = 0.5
        confidence = round(0.82 * title_score + 0.18 * year_score, 4)
        candidates.append(
            MatchCandidate(int(result["id"]), candidate_title, candidate_year, confidence)
        )
    candidates.sort(key=lambda item: item.confidence, reverse=True)
    if not candidates or candidates[0].confidence < accept_threshold:
        return MatchResult("unresolved", None, tuple(candidates[:5]))
    if (
        len(candidates) > 1
        and candidates[0].confidence - candidates[1].confidence < ambiguity_margin
    ):
        return MatchResult("ambiguous", None, tuple(candidates[:5]))
    return MatchResult("matched", candidates[0], tuple(candidates[:5]))
