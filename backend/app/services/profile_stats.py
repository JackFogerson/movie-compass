from __future__ import annotations

import re
from collections import defaultdict
from math import sqrt
from statistics import mean

from app.services.certifications import UNKNOWN_CERTIFICATION, us_certification
from recommendation.ranking.current_catalog import classify_popularity

LANGUAGE_NAMES = {
    "aa": "Afar-language",
    "ab": "Abkhazian-language",
    "af": "Afrikaans-language",
    "ar": "Arabic-language",
    "bn": "Bengali-language",
    "cn": "Cantonese-language",
    "cs": "Czech-language",
    "da": "Danish-language",
    "de": "German-language",
    "el": "Greek-language",
    "en": "English-language",
    "es": "Spanish-language",
    "fa": "Persian-language",
    "fi": "Finnish-language",
    "fr": "French-language",
    "he": "Hebrew-language",
    "hi": "Hindi-language",
    "hu": "Hungarian-language",
    "id": "Indonesian-language",
    "it": "Italian-language",
    "ja": "Japanese-language",
    "kn": "Kannada-language",
    "ko": "Korean-language",
    "lv": "Latvian-language",
    "mk": "Macedonian-language",
    "nl": "Dutch-language",
    "no": "Norwegian-language",
    "pl": "Polish-language",
    "pt": "Portuguese-language",
    "ru": "Russian-language",
    "sh": "Serbo-Croatian-language",
    "sr": "Serbian-language",
    "sv": "Swedish-language",
    "ta": "Tamil-language",
    "te": "Telugu-language",
    "th": "Thai-language",
    "tl": "Tagalog-language",
    "tr": "Turkish-language",
    "xx": "No spoken language",
    "zxx": "No spoken language",
    "zh": "Chinese-language",
}
POPULARITY_NAMES = {
    "blockbuster": "Blockbusters",
    "popular": "Popular releases",
    "cult_classic": "Cult classics",
    "under_the_radar": "Under the radar",
    "unknown": "Unknown or emerging",
}
METADATA_FILTER_CATEGORIES = {
    "themes": "Themes and topics",
    "directors": "Directors",
    "actors": "Actors",
    "languages": "Languages",
    "countries": "Production countries",
    "companies": "Production companies",
}


def _named_values(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [
        str(value.get("name")).strip()
        for value in values
        if isinstance(value, dict) and str(value.get("name") or "").strip()
    ]


def _language_label(value: object) -> str:
    code = str(value or "").strip().casefold()
    if not code:
        return "Language not listed"
    return LANGUAGE_NAMES.get(code, f"{code.upper()}-language (unrecognized code)")


def metadata_match_stat_target(match: str) -> tuple[str, str] | None:
    """Map a ranking explanation token to its matching profile-stat category."""
    kind, separator, raw_value = str(match).partition(":")
    if not separator or not raw_value.strip():
        return None
    value = raw_value.strip()
    kind = kind.strip().casefold()
    if kind in {"director", "cast member"} and not any(
        len(part) > 1 for part in value.replace("-", " ").split()
    ):
        return None
    if kind == "genre":
        return "genres", value
    if kind == "story/theme":
        return "themes", value
    if kind == "director":
        return "directors", value
    if kind == "cast member":
        return "actors", value
    if kind == "release era":
        return "decades", value
    if kind == "original language":
        return "languages", _language_label(value)
    if kind == "production country":
        return "countries", value
    if kind == "production company":
        return "companies", value
    if kind == "runtime":
        return "runtimes", value
    if kind == "content rating":
        return "certifications", value
    return None


def category_label_matches(label: str, requested: str) -> bool:
    """Match exact labels and legacy model labels that omitted punctuation."""

    def normalize(value: str) -> str:
        return re.sub(r"[^\w]+", " ", value.casefold()).strip()

    return label.casefold() == requested.casefold() or normalize(label) == normalize(requested)


def _summarize(
    values: dict[str, list[float]],
    profile_average: float,
    *,
    minimum: int,
    limit: int | None = 8,
) -> list[dict]:
    rows = []
    for label, ratings in values.items():
        if len(ratings) < minimum:
            continue
        observed = mean(ratings)
        # A small profile-average prior keeps one or two titles from looking definitive.
        expected = (sum(ratings) + 3 * profile_average) / (len(ratings) + 3)
        rows.append(
            {
                "label": label,
                "expected_rating": round(expected, 2),
                "observed_average": round(observed, 2),
                "difference_from_profile": round(expected - profile_average, 2),
                "films": len(ratings),
            }
        )
    rows.sort(key=lambda item: (item["expected_rating"], item["films"]), reverse=True)
    if limit is None or len(rows) <= limit:
        return rows
    top_count = (limit + 1) // 2
    bottom_count = limit - top_count
    return [*rows[:top_count], *rows[-bottom_count:]]


def build_public_opinion_splits(
    movies: list[dict],
    details_by_id: dict[int, dict],
    *,
    limit: int = 5,
    minimum_public_votes: int = 25,
) -> dict:
    """Compare a profile's ratings with TMDB's public average on the same 5-star scale."""
    comparisons = []
    for movie in movies:
        tmdb_id = movie.get("tmdb_id")
        if tmdb_id is None or movie.get("rating") is None:
            continue
        details = details_by_id.get(int(tmdb_id), {})
        vote_average = float(details.get("vote_average") or 0.0)
        vote_count = int(details.get("vote_count") or 0)
        if vote_average <= 0 or vote_count < minimum_public_votes:
            continue
        personal_rating = float(movie["rating"])
        public_rating = vote_average / 2.0
        comparisons.append(
            {
                "tmdb_id": int(tmdb_id),
                "title": str(movie.get("title") or details.get("title") or "Untitled"),
                "year": movie.get("year"),
                "personal_rating": round(personal_rating, 2),
                "public_rating": round(public_rating, 2),
                "difference": round(personal_rating - public_rating, 2),
                "public_votes": vote_count,
            }
        )
    underrated = sorted(
        (item for item in comparisons if item["difference"] > 0),
        key=lambda item: (item["difference"], item["public_votes"]),
        reverse=True,
    )[:limit]
    overrated = sorted(
        (item for item in comparisons if item["difference"] < 0),
        key=lambda item: (item["difference"], -item["public_votes"]),
    )[:limit]
    return {
        "underrated": underrated,
        "overrated": overrated,
        "eligible_films": len(comparisons),
        "minimum_public_votes": minimum_public_votes,
        "explanation": (
            "Underrated means you rated it higher than TMDB viewers; overrated means you "
            "rated it lower. Both ratings use a five-star scale."
        ),
    }


def movie_category_labels(movie: dict, details: dict) -> dict[str, tuple[str, ...]]:
    """Return the exact category labels used by both stats and drill-down results."""
    year = movie.get("year")
    runtime = details.get("runtime") or movie.get("runtime")
    keyword_block = details.get("keywords") or {}
    keywords = keyword_block.get("keywords", []) if isinstance(keyword_block, dict) else []
    crew = (details.get("credits") or {}).get("crew", [])
    cast = (details.get("credits") or {}).get("cast", [])
    language = _language_label(details.get("original_language"))
    vote_count = int(details.get("vote_count") or 0)
    runtime_label = None
    if runtime:
        runtime = int(runtime)
        runtime_label = (
            "Under 90 minutes"
            if runtime < 90
            else "90–119 minutes"
            if runtime < 120
            else "120–149 minutes"
            if runtime < 150
            else "150+ minutes"
        )
    return {
        "genres": tuple(sorted(set(_named_values(details.get("genres"))))),
        "themes": tuple(sorted({name.capitalize() for name in _named_values(keywords)})),
        "decades": (f"{int(year) // 10 * 10}s",) if year else (),
        "directors": tuple(
            sorted(
                {
                    str(person.get("name"))
                    for person in crew
                    if isinstance(person, dict)
                    and person.get("job") == "Director"
                    and person.get("name")
                }
            )
        ),
        "actors": tuple(sorted(set(_named_values(cast)[:8]))),
        "languages": (language,),
        "countries": tuple(sorted(set(_named_values(details.get("production_countries"))))),
        "companies": tuple(sorted(set(_named_values(details.get("production_companies"))))),
        "runtimes": (runtime_label,) if runtime_label else (),
        "popularity": (
            POPULARITY_NAMES[classify_popularity(int(year) if year else None, vote_count)],
        ),
        "certifications": (us_certification(details) or UNKNOWN_CERTIFICATION,),
    }


def metadata_filter_labels(details: dict, category: str) -> tuple[str, ...]:
    """Return catalog labels for one filterable rich-metadata category."""
    if category not in METADATA_FILTER_CATEGORIES:
        raise ValueError(f"Unsupported metadata filter category: {category}")
    release = str(details.get("release_date") or details.get("first_air_date") or "")
    year = int(release[:4]) if release[:4].isdigit() else None
    movie = {"year": year, "runtime": details.get("runtime")}
    return movie_category_labels(movie, details)[category]


def matches_metadata_filter(details: dict, category: str, value: str) -> bool:
    """Match a selected suggestion using the same labels shown in profile statistics."""
    if category == "companies":
        requested = re.sub(r"[^\w]+", "", value.casefold())
        return bool(requested) and any(
            requested in re.sub(r"[^\w]+", "", label.casefold())
            or re.sub(r"[^\w]+", "", label.casefold()) in requested
            for label in metadata_filter_labels(details, category)
        )
    return any(
        category_label_matches(label, value) for label in metadata_filter_labels(details, category)
    )


def metadata_filter_options(
    details_by_id: dict[str, dict],
    category: str,
    *,
    query: str = "",
    limit: int = 12,
    option_index: dict[str, dict[str, int]] | None = None,
) -> dict:
    """Build stable catalog-wide suggestions, favoring prefix matches and common labels."""
    if category not in METADATA_FILTER_CATEGORIES:
        raise ValueError(f"Unsupported metadata filter category: {category}")
    counts = (option_index or build_metadata_filter_index(details_by_id))[category]
    normalized_query = query.casefold().strip()
    matches = [
        (label, count)
        for label, count in counts.items()
        if not normalized_query or normalized_query in label.casefold()
    ]
    matches.sort(
        key=lambda item: (
            0 if item[0].casefold().startswith(normalized_query) else 1,
            -item[1],
            item[0].casefold(),
        )
    )
    option_mode = "select" if len(counts) <= 18 else "search"
    returned = matches if option_mode == "select" else matches[:limit]
    return {
        "category": category,
        "label": METADATA_FILTER_CATEGORIES[category],
        "mode": option_mode,
        "total": len(counts),
        "query": query,
        "options": [{"value": label, "films": count} for label, count in returned],
    }


def build_metadata_filter_index(
    details_by_id: dict[str, dict],
) -> dict[str, dict[str, int]]:
    """Precompute catalog trait counts so each type-ahead keystroke stays inexpensive."""
    index: dict[str, dict[str, int]] = {
        category: defaultdict(int) for category in METADATA_FILTER_CATEGORIES
    }
    for details in details_by_id.values():
        if not isinstance(details, dict) or details.get("missing") is True:
            continue
        for category in METADATA_FILTER_CATEGORIES:
            for label in metadata_filter_labels(details, category):
                index[category][label] += 1
    return {category: dict(counts) for category, counts in index.items()}


def build_taste_breakdown(
    rated_movies: list[dict],
    details_by_id: dict[int, dict],
    *,
    limit: int | None = 8,
    include_singletons: bool = False,
) -> dict:
    ratings = [float(item["rating"]) for item in rated_movies]
    if not ratings:
        return {}
    profile_average = mean(ratings)
    categories: dict[str, dict[str, list[float]]] = {
        name: defaultdict(list)
        for name in (
            "genres",
            "themes",
            "decades",
            "directors",
            "actors",
            "languages",
            "countries",
            "companies",
            "runtimes",
            "popularity",
            "certifications",
        )
    }
    for movie in rated_movies:
        rating = float(movie["rating"])
        details = details_by_id.get(int(movie["tmdb_id"]), {}) if movie.get("tmdb_id") else {}
        for category, labels in movie_category_labels(movie, details).items():
            for label in labels:
                categories[category][label].append(rating)

    standard_deviation = sqrt(mean((rating - profile_average) ** 2 for rating in ratings))
    unknown_certifications = len(categories["certifications"].get(UNKNOWN_CERTIFICATION, []))
    known_certifications = len(ratings) - unknown_certifications
    repeated_minimum = 1 if include_singletons else 2
    return {
        "profile_average": round(profile_average, 2),
        "explanation": (
            "Expected ratings describe a generic movie with that trait. They blend the observed "
            "average back toward this profile's usual rating when evidence is limited."
        ),
        "genres": _summarize(
            categories["genres"], profile_average, minimum=repeated_minimum, limit=limit
        ),
        "themes": _summarize(
            categories["themes"], profile_average, minimum=repeated_minimum, limit=limit
        ),
        "decades": _summarize(categories["decades"], profile_average, minimum=1, limit=limit),
        "directors": _summarize(
            categories["directors"], profile_average, minimum=repeated_minimum, limit=limit
        ),
        "actors": _summarize(
            categories["actors"], profile_average, minimum=repeated_minimum, limit=limit
        ),
        "languages": _summarize(
            categories["languages"], profile_average, minimum=repeated_minimum, limit=limit
        ),
        "countries": _summarize(
            categories["countries"], profile_average, minimum=repeated_minimum, limit=limit
        ),
        "companies": _summarize(
            categories["companies"], profile_average, minimum=repeated_minimum, limit=limit
        ),
        "runtimes": _summarize(
            categories["runtimes"], profile_average, minimum=repeated_minimum, limit=limit
        ),
        "popularity": _summarize(
            categories["popularity"], profile_average, minimum=repeated_minimum, limit=limit
        ),
        "certifications": _summarize(
            categories["certifications"], profile_average, minimum=1, limit=limit
        ),
        "fun_facts": {
            "rating_spread": round(standard_deviation, 2),
            "five_star_films": sum(rating == 5 for rating in ratings),
            "two_stars_or_lower": sum(rating <= 2 for rating in ratings),
            "genres_explored": len(categories["genres"]),
            "decades_explored": len(categories["decades"]),
            "languages_explored": len(categories["languages"]),
            "countries_explored": len(categories["countries"]),
            "companies_explored": len(categories["companies"]),
            "certification_known_films": known_certifications,
            "certification_unknown_films": unknown_certifications,
            "certification_coverage_percent": round(known_certifications / len(ratings) * 100, 1),
        },
    }
