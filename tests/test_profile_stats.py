from app.services.profile_stats import (
    build_taste_breakdown,
    category_label_matches,
    matches_metadata_filter,
    metadata_filter_options,
    metadata_match_stat_target,
    movie_category_labels,
)


def test_language_stats_use_readable_consistent_labels() -> None:
    expected = {
        "en": "English-language",
        "lv": "Latvian-language",
        "aa": "Afar-language",
        "ab": "Abkhazian-language",
        "xx": "No spoken language",
        "": "Language not listed",
        "qz": "QZ-language (unrecognized code)",
    }

    for code, label in expected.items():
        result = movie_category_labels({}, {"original_language": code})
        assert result["languages"] == (label,)


def test_production_countries_and_ranking_descriptors_use_stats_labels() -> None:
    labels = movie_category_labels(
        {},
        {
            "original_language": "fr",
            "production_countries": [
                {"iso_3166_1": "FR", "name": "France"},
                {"iso_3166_1": "IT", "name": "Italy"},
            ],
        },
    )

    assert labels["countries"] == ("France", "Italy")
    assert metadata_match_stat_target("genre: crime") == ("genres", "crime")
    assert metadata_match_stat_target("story/theme: organized crime") == (
        "themes",
        "organized crime",
    )
    assert metadata_match_stat_target("original language: fr") == (
        "languages",
        "French-language",
    )
    assert category_label_matches("Los angeles, california", "los angeles california")
    assert category_label_matches("Vikings (norsemen)", "vikings norsemen")


def test_theme_stats_keep_keywords_beyond_the_old_twenty_four_item_limit() -> None:
    keywords = [{"name": f"theme {index}"} for index in range(30)]

    labels = movie_category_labels({}, {"keywords": {"keywords": keywords}})

    assert "Theme 29" in labels["themes"]


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
            "production_countries": [{"name": "United States of America"}],
            "production_companies": [{"name": "Pixar Animation Studios"}],
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
            "production_countries": [{"name": "United States of America"}],
            "production_companies": [{"name": "Pixar Animation Studios"}],
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
            "production_countries": [{"name": "France"}],
            "production_companies": [{"name": "StudioCanal"}],
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
    assert result["countries"][0]["label"] == "United States of America"
    assert result["companies"][0]["label"] == "Pixar Animation Studios"
    assert result["fun_facts"]["certification_known_films"] == 2
    assert result["fun_facts"]["certification_unknown_films"] == 1
    assert result["fun_facts"]["certification_coverage_percent"] == 66.7
    assert result["fun_facts"]["decades_explored"] == 2
    assert result["fun_facts"]["countries_explored"] == 2
    assert result["fun_facts"]["companies_explored"] == 2


def test_production_company_ranking_descriptor_maps_to_stats() -> None:
    assert metadata_match_stat_target("production company: Pixar Animation Studios") == (
        "companies",
        "Pixar Animation Studios",
    )


def test_catalog_metadata_filters_offer_dropdowns_and_typeahead_suggestions() -> None:
    details = {
        str(index): {
            "keywords": {"keywords": [{"name": f"theme {index}"}]},
            "production_companies": [{"name": "Blumhouse Productions"}],
        }
        for index in range(20)
    }
    details["20"] = {
        "keywords": {
            "keywords": [
                {"name": "halloween"},
                {"name": "high school"},
                {"name": "happy"},
            ]
        },
        "production_companies": [{"name": "Pixar Animation Studios"}],
    }

    company_options = metadata_filter_options(details, "companies")
    theme_options = metadata_filter_options(details, "themes", query="h")

    assert company_options["mode"] == "select"
    assert {item["value"] for item in company_options["options"]} == {
        "Blumhouse Productions",
        "Pixar Animation Studios",
    }
    assert theme_options["mode"] == "search"
    assert {item["value"] for item in theme_options["options"]} >= {
        "Halloween",
        "High school",
        "Happy",
    }
    assert matches_metadata_filter(details["20"], "themes", "Halloween")
    assert not matches_metadata_filter(details["20"], "themes", "haunted house")


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


def test_company_filter_matches_spacing_and_related_company_names() -> None:
    details = {
        "production_companies": [
            {"name": "Lions Gate Films"},
            {"name": "Lionsgate UK"},
        ]
    }

    assert matches_metadata_filter(details, "companies", "Lionsgate")
    assert not matches_metadata_filter(details, "companies", "Pixar")
