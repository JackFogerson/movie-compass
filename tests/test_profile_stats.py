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
        },
        2: {
            "genres": [{"name": "Science Fiction"}],
            "keywords": {"keywords": [{"name": "space travel"}]},
            "original_language": "en",
        },
        3: {
            "genres": [{"name": "Drama"}],
            "keywords": {"keywords": [{"name": "grief"}]},
            "original_language": "fr",
        },
    }

    result = build_taste_breakdown(movies, details)

    science_fiction = next(
        item for item in result["genres"] if item["label"] == "Science Fiction"
    )
    assert result["profile_average"] == 3.33
    assert science_fiction["observed_average"] == 4.5
    assert 3.33 < science_fiction["expected_rating"] < 4.5
    assert result["fun_facts"]["decades_explored"] == 2
