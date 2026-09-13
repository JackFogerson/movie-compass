from app.services.profile_stats import build_taste_breakdown


def test_taste_breakdown_shrinks_feature_expectations_toward_profile_average() -> None:
    movies = [
        {"tmdb_id": 1, "rating": 5.0, "year": 1999, "runtime": 100},
        {"tmdb_id": 2, "rating": 4.0, "year": 1995, "runtime": 110},
        {"tmdb_id": 3, "rating": 1.0, "year": 2020, "runtime": 160},
    ]
    details = {
        1: {
            "genres": [{"name": "Science Fiction"}],
            "keywords": {"keywords": [{"name": "space travel"}]},
            "original_language": "en",
            "vote_count": 15_000,
            "credits": {"cast": [{"name": "Favorite Actor"}]},
            "release_dates": {
                "results": [
                    {"iso_3166_1": "US", "release_dates": [{"type": 3, "certification": "PG-13"}]}
                ]
            },
        },
        2: {
            "genres": [{"name": "Science Fiction"}],
            "keywords": {"keywords": [{"name": "space travel"}]},
            "original_language": "en",
            "vote_count": 12_000,
            "credits": {"cast": [{"name": "Favorite Actor"}]},
            "release_dates": {
                "results": [
                    {"iso_3166_1": "US", "release_dates": [{"type": 3, "certification": "PG-13"}]}
                ]
            },
        },
        3: {
            "genres": [{"name": "Drama"}],
            "keywords": {"keywords": [{"name": "grief"}]},
            "original_language": "fr",
            "vote_count": 30,
            "credits": {"cast": [{"name": "Another Actor"}]},
        },
    }

    result = build_taste_breakdown(movies, details)

    science_fiction = next(item for item in result["genres"] if item["label"] == "Science Fiction")
    assert result["profile_average"] == 3.33
    assert science_fiction["observed_average"] == 4.5
    assert 3.33 < science_fiction["expected_rating"] < 4.5
    assert result["actors"][0]["label"] == "Favorite Actor"
    assert result["popularity"][0]["label"] == "Blockbusters"
    assert result["certifications"][0]["label"] == "PG-13"
    assert result["fun_facts"]["certification_known_films"] == 2
    assert result["fun_facts"]["certification_unknown_films"] == 1
    assert result["fun_facts"]["certification_coverage_percent"] == 66.7
    assert result["fun_facts"]["decades_explored"] == 2


def test_full_taste_breakdown_keeps_singletons_without_truncation() -> None:
    movies = [
        {"tmdb_id": index, "rating": 0.5 + (index % 10) * 0.5, "year": 2000}
        for index in range(1, 61)
    ]
    details = {
        index: {"keywords": {"keywords": [{"name": f"theme {index}"}]}} for index in range(1, 61)
    }

    result = build_taste_breakdown(
        movies,
        details,
        limit=None,
        include_singletons=True,
    )

    assert len(result["themes"]) == 60
    assert all(item["films"] == 1 for item in result["themes"])
