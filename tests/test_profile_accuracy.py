from app.services.profile_accuracy import _rating_surprises


def test_rating_surprises_aggregate_only_held_out_predictions() -> None:
    errors = [
        {"movie_id": 1, "actual": 4.5, "hybrid": 3.0},
        {"movie_id": 1, "actual": 4.5, "hybrid": 3.5},
        {"movie_id": 2, "actual": 1.5, "hybrid": 4.0},
    ]

    result = _rating_surprises(
        errors,
        identifier="movie_id",
        titles={
            1: {"title": "Pleasant Surprise", "year": 2001},
            2: {"title": "Disappointment", "year": 2002},
        },
    )

    assert result is not None
    high = result["highest_actual_minus_expected"]
    low = result["lowest_actual_minus_expected"]
    assert high == {
        "id": 1,
        "title": "Pleasant Surprise",
        "year": 2001,
        "actual_rating": 4.5,
        "expected_rating": 3.25,
        "difference": 1.25,
        "held_out_tests": 2,
    }
    assert low["title"] == "Disappointment"
    assert low["difference"] == -2.5
