from recommendation.baselines.tmdb_content import (
    TmdbContentModel,
    _display_structured_value,
    metadata_text,
)


def _details(index: int) -> dict:
    return {
        "release_date": f"202{index % 5}-01-01",
        "original_language": "en",
        "runtime": 105,
        "overview": f"Story number {index} about memory and identity",
        "genres": [{"name": "Drama" if index % 2 else "Horror"}],
        "production_countries": [{"name": "United States of America"}],
        "production_companies": [{"name": "Pixar Animation Studios"}],
        "release_dates": {
            "results": [
                {
                    "iso_3166_1": "US",
                    "release_dates": [{"type": 3, "certification": "PG-13"}],
                }
            ]
        },
        "keywords": {"keywords": [{"name": "memory"}]},
        "credits": {
            "crew": [{"job": "Director", "name": f"Director {index % 3}"}],
            "cast": [{"name": f"Actor {index % 4}"}],
        },
    }


def test_metadata_text_includes_rich_features() -> None:
    text = metadata_text(_details(1))
    assert "genre_drama" in text
    assert "keyword_memory" in text
    assert "director_director_1" in text
    assert "cast_actor_1" in text
    assert "country_united_states_of_america" in text
    assert "company_pixar_animation_studios" in text
    assert "runtime_90_119_minutes" in text
    assert "certification_pg-13" in text


def test_metadata_text_keeps_initialed_cast_name_in_one_feature() -> None:
    details = _details(1)
    details["credits"]["cast"] = [{"name": "J.K. Simmons"}]

    text = metadata_text(details)

    assert "cast_j_k_simmons" in text
    assert "cast_j." not in text
    assert _display_structured_value(details, "cast", "j_k_simmons") == "j.k. simmons"


def test_explanation_value_recovers_keyword_punctuation() -> None:
    details = _details(1)
    details["keywords"]["keywords"] = [{"name": "Los Angeles, California"}]

    assert (
        _display_structured_value(details, "keyword", "los_angeles_california")
        == "los angeles, california"
    )


def test_tmdb_content_model_scores_new_metadata() -> None:
    details = {index: _details(index) for index in range(1, 13)}
    ratings = {index: 1.0 if index % 2 else 5.0 for index in details}
    model = TmdbContentModel.fit(details, ratings)

    result = model.predict({100: _details(2), 101: _details(1)})

    assert result[100] > result[101]
