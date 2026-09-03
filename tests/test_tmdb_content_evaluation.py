from ml.evaluation.tmdb_content import evaluate_tmdb_content


def test_rich_content_evaluation_reports_all_ratings() -> None:
    details = {
        index: {
            "release_date": "2024-01-01",
            "original_language": "en",
            "overview": "bright hopeful adventure" if index % 2 else "grim bleak horror",
            "genres": [{"name": "Adventure" if index % 2 else "Horror"}],
            "keywords": {"keywords": []},
            "credits": {"crew": [], "cast": []},
        }
        for index in range(1, 31)
    }
    ratings = {index: 5.0 if index % 2 else 1.0 for index in details}

    result = evaluate_tmdb_content(details, ratings, seeds=(1, 2))

    assert result.ratings == 30
    assert result.rich_content_mae < result.mean_baseline_mae
