from recommendation.baselines.review_themes import ReviewThemeModel


def _details(overview: str) -> dict:
    return {
        "release_date": "2024-01-01",
        "original_language": "en",
        "overview": overview,
        "genres": [],
        "keywords": {"keywords": []},
        "credits": {"crew": [], "cast": []},
    }


def test_review_themes_prefer_terms_from_high_rated_reviews() -> None:
    reviews = {
        index: (
            "space adventure wonder imaginative future"
            if index % 2
            else "boring wedding romance predictable"
        )
        for index in range(1, 13)
    }
    ratings = {index: 5.0 if index % 2 else 1.0 for index in reviews}
    candidates = {
        100: _details("an imaginative space adventure in the future"),
        101: _details("a predictable wedding romance"),
    }
    model = ReviewThemeModel.fit(reviews, ratings, candidates)

    scores = model.affinities(candidates)

    assert scores[100] > scores[101]
    assert "space" in model.explanation_terms(candidates[100])
