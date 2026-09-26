from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock

from app.services.certifications import us_certification
from ingestion.letterboxd.parser import normalize_title
from ingestion.tmdb.client import TmdbClient, is_tv_catalog_id, normalize_tv_details

_CACHE_LOCK = Lock()
_DISPLAY_SCHEMA = 3
_PROVIDER_TYPES = {
    "flatrate": "subscription",
    "free": "free",
    "ads": "free with ads",
    "rent": "rent",
    "buy": "buy",
}


def mood_labels(details: dict, *, limit: int = 2) -> list[str]:
    genres = {str(item.get("name") or "") for item in details.get("genres", [])}
    rules = [
        ("Scary", {"Horror"}),
        ("Funny", {"Comedy"}),
        ("Tense", {"Thriller", "Mystery", "Crime"}),
        ("Adventurous", {"Adventure", "Fantasy"}),
        ("High-energy", {"Action"}),
        ("Imaginative", {"Science Fiction", "Sci-Fi", "Animation"}),
        ("Heartfelt", {"Romance", "Family"}),
        ("Thoughtful", {"Documentary", "History"}),
        ("Emotional", {"Drama"}),
    ]
    labels = [label for label, matches in rules if genres.intersection(matches)]
    return labels[:limit]


def streaming_options(details: dict, country: str) -> tuple[list[dict], str | None]:
    region = details.get("watch_providers", {}).get("results", {}).get(country.upper(), {})
    options = []
    seen: set[tuple[str, str]] = set()
    for source_type, readable_type in _PROVIDER_TYPES.items():
        for provider in region.get(source_type, []):
            name = str(provider.get("provider_name") or "").strip()
            key = (name, readable_type)
            if not name or key in seen:
                continue
            seen.add(key)
            options.append(
                {
                    "service": name,
                    "type": readable_type,
                    "logo_path": provider.get("logo_path"),
                }
            )
    return options, region.get("link")


def _is_fresh(entry: dict, now: datetime) -> bool:
    if entry.get("display_schema") != _DISPLAY_SCHEMA:
        return False
    raw = entry.get("fetched_at")
    if not raw:
        return False
    try:
        fetched = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    return now - fetched <= timedelta(hours=24)


def _tv_match(results: list[dict], title: str, year: int | None) -> dict | None:
    normalized = normalize_title(title)
    candidates = []
    for result in results:
        candidate_title = result.get("name") or result.get("original_name") or ""
        if normalize_title(candidate_title) != normalized:
            continue
        first_air_date = str(result.get("first_air_date") or "")
        candidate_year = (
            int(first_air_date[:4])
            if len(first_air_date) >= 4 and first_air_date[:4].isdigit()
            else None
        )
        year_distance = abs(candidate_year - year) if candidate_year and year else 0
        candidates.append((year_distance, result))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _fetch_display_details(
    api_key: str,
    tmdb_id: int,
    title: str,
    year: int | None,
) -> tuple[int, dict | None]:
    client = TmdbClient(api_key)
    media_type = "movie"
    try:
        if is_tv_catalog_id(tmdb_id):
            media_type = "tv"
            raw = normalize_tv_details(
                client.tv_details(
                    abs(tmdb_id),
                    "keywords,watch/providers,credits,content_ratings",
                )
            )
        else:
            try:
                raw = client.movie_details(
                    tmdb_id,
                    "keywords,watch/providers,credits,release_dates",
                )
            except Exception:
                match = _tv_match(client.search_tv(title, year), title, year)
                if match is None:
                    return tmdb_id, None
                media_type = "tv"
                raw = normalize_tv_details(
                    client.tv_details(
                        int(match["id"]),
                        "keywords,watch/providers,credits,content_ratings",
                    )
                )
    except Exception:
        return tmdb_id, None
    finally:
        client.close()
    runtime = raw.get("runtime")
    credits = raw.get("credits") or {}
    directors = []
    for person in credits.get("crew") or []:
        name = str(person.get("name") or "").strip()
        if person.get("job") == "Director" and name and name not in directors:
            directors.append(name)
    cast = [
        str(person.get("name") or "").strip()
        for person in sorted(credits.get("cast") or [], key=lambda person: person.get("order", 999))
        if str(person.get("name") or "").strip()
    ][:6]
    return tmdb_id, {
        "display_schema": _DISPLAY_SCHEMA,
        "id": abs(int(raw["id"])) if media_type == "tv" and raw.get("id") else raw.get("id"),
        "media_type": media_type,
        "title": raw.get("title") or raw.get("name"),
        "original_title": raw.get("original_title") or raw.get("original_name"),
        "release_date": raw.get("release_date") or raw.get("first_air_date"),
        "overview": raw.get("overview"),
        "poster_path": raw.get("poster_path"),
        "backdrop_path": raw.get("backdrop_path"),
        "directors": directors,
        "cast": cast,
        "runtime": runtime,
        "runtime_label": raw.get("runtime_label") if media_type == "tv" else None,
        "original_language": raw.get("original_language"),
        "popularity": raw.get("popularity"),
        "vote_average": raw.get("vote_average"),
        "vote_count": raw.get("vote_count"),
        "genres": raw.get("genres", []),
        "keywords": raw.get("keywords", {}),
        "watch_providers": raw.get("watch/providers", {}),
        "certification": us_certification(raw),
        "fetched_at": datetime.now(UTC).isoformat(),
    }


def enrich_display_metadata(
    report: dict,
    *,
    api_key: str,
    cache_path: Path,
    country: str = "US",
) -> dict:
    """Attach display-only runtime, mood, and regional streaming information."""
    sections = [
        report.get("recommendations", []),
        report.get("lowest_recommendations", []),
        report.get("most_divisive", []),
        report.get("results", []),
    ]
    movies = [movie for section in sections for movie in section]
    movie_lookup = {
        int(movie["tmdb_id"]): (
            str(movie.get("title") or ""),
            int(movie["year"]) if movie.get("year") is not None else None,
        )
        for movie in movies
        if movie.get("tmdb_id") is not None
    }
    ids = set(movie_lookup)
    if not ids:
        report["streaming_country"] = country.upper()
        return report

    with _CACHE_LOCK:
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cached = {}
        else:
            cached = {}
    now = datetime.now(UTC)
    missing = [tmdb_id for tmdb_id in ids if not _is_fresh(cached.get(str(tmdb_id), {}), now)]
    if missing and api_key:
        with ThreadPoolExecutor(max_workers=min(6, len(missing))) as executor:
            fetched = dict(
                executor.map(
                    lambda value: _fetch_display_details(
                        api_key,
                        value,
                        movie_lookup[value][0],
                        movie_lookup[value][1],
                    ),
                    missing,
                )
            )
        for tmdb_id, details in fetched.items():
            if details is not None:
                cached[str(tmdb_id)] = details
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with _CACHE_LOCK:
            cache_path.write_text(json.dumps(cached, indent=2), encoding="utf-8")

    for movie in movies:
        details = cached.get(str(movie.get("tmdb_id")), {})
        movie["runtime"] = details.get("runtime")
        movie["runtime_label"] = details.get("runtime_label")
        poster_path = details.get("poster_path")
        movie["poster_url"] = (
            f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else None
        )
        movie["synopsis"] = details.get("overview")
        movie["directors"] = details.get("directors", [])
        movie["cast"] = details.get("cast", [])
        movie["moods"] = mood_labels(details)
        movie["certification"] = details.get("certification")
        options, link = streaming_options(details, country)
        movie["streaming"] = options
        movie["streaming_link"] = link
        movie["streaming_country"] = country.upper()
    report["streaming_country"] = country.upper()
    report["streaming_attribution"] = "Streaming availability data supplied by JustWatch."
    return report
