from recommendation.baselines.tmdb_content import TmdbContentModel


def _details(index: int, genre: str) -> dict:
    return {
        "id": index,
        "genres": [{"name": genre}],
        "keywords": {"keywords": [{"name": "haunted house"}]},
        "credits": {
            "crew": [{"job": "Director", "name": "Jane Example"}],
            "cast": [{"name": "Alex Actor"}],
        },
        "release_date": f"20{10 + index:02d}-01-01",
        "original_language": "en",
        "overview": "A family encounters a mystery.",
    }


def test_explanation_features_are_human_readable_structured_matches() -> None:
    details = {index: _details(index, "Horror" if index < 5 else "Comedy") for index in range(10)}
    ratings = {index: 5.0 if index < 5 else 1.0 for index in range(10)}
    model = TmdbContentModel.fit(details, ratings)

    matches = model.explanation_features(_details(99, "Horror"))

    assert "genre: horror" in matches
    assert all("_" not in value for value in matches)
