from __future__ import annotations

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
        "themes": tuple(sorted({name.capitalize() for name in _named_values(keywords)[:24]})),
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
        "runtimes": (runtime_label,) if runtime_label else (),
        "popularity": (
            POPULARITY_NAMES[classify_popularity(int(year) if year else None, vote_count)],
        ),
        "certifications": (us_certification(details) or UNKNOWN_CERTIFICATION,),
    }


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
    unknown_certifications = len(
        categories["certifications"].get(UNKNOWN_CERTIFICATION, [])
    )
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
            "certification_known_films": known_certifications,
            "certification_unknown_films": unknown_certifications,
            "certification_coverage_percent": round(
                known_certifications / len(ratings) * 100, 1
            ),
        },
    }
