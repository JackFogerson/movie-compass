import numpy as np
import pandas as pd
from scipy import sparse

from recommendation.baselines.content import ContentBaseline
from recommendation.baselines.popularity import PopularityBaseline
from recommendation.collaborative.latent_factor import LatentFactorModel
from recommendation.ranking.current_catalog import (
    _candidate_frame,
    classify_popularity,
    humanize_caution_matches,
    humanize_metadata_matches,
    preselect_movielens_candidates,
    rank_current_candidates,
)


def test_tv_namespace_never_collides_with_a_movielens_movie_id() -> None:
    frame = _candidate_frame(
        [{"id": -3022, "media_type": "tv", "title": "Rugrats", "genres": []}],
        {3022: 99},
    )

    assert frame.iloc[0]["tmdb_id"] == -3022
    assert frame.iloc[0]["movieId"] == -3022
    assert frame.iloc[0]["media_type"] == "tv"


def test_current_ranking_includes_and_labels_tmdb_only_movies() -> None:
    catalog = pd.DataFrame(
        {
            "movieId": [1, 2, 3],
            "genres": ["Drama", "Horror|Thriller", "Comedy"],
            "year": [2020, 2021, 2022],
        }
    )
    personal = {1: 2.0, 2: 5.0}
    content = ContentBaseline.fit(catalog, personal)
    matrix = sparse.csr_matrix(np.array([[2.0, 5.0, 3.0], [3.0, 4.5, 3.5]]))
    movie_ids = np.array([1, 2, 3])
    popularity = PopularityBaseline.fit(matrix, movie_ids)
    collaborative = LatentFactorModel.fit(matrix, movie_ids, factors=1)
    factors = collaborative.fit_personal(personal)
    candidates = [
        {
            "id": 100,
            "title": "New Horror",
            "release_date": "2026-08-01",
            "genre_ids": [27, 53],
            "vote_average": 8.0,
            "vote_count": 100,
        },
        {
            "id": 200,
            "title": "Already Watched",
            "release_date": "2026-07-01",
            "genre_ids": [18],
            "vote_average": 9.0,
            "vote_count": 1000,
        },
    ]

    ranked = rank_current_candidates(
        candidates,
        excluded_tmdb_ids={200},
        movielens_by_tmdb={},
        content=content,
        collaborative=collaborative,
        personal_factors=factors,
        popularity=popularity,
        user_mean=3.5,
        review_affinities={100: 0.25},
        review_terms={100: ("space", "adventure")},
        metadata_matches={100: ("genre: horror", "story/theme: survival")},
    )

    assert [item.tmdb_id for item in ranked] == [100]
    assert ranked[0].score_mode == "cold_start"
    assert ranked[0].movielens_id is None
    assert ranked[0].review_theme_affinity == 0.25
    assert "space" in ranked[0].explanation[1]
    serialized = ranked[0].to_dict()
    assert serialized["expected_rating"] == ranked[0].score
    assert serialized["ranking_expectation"]["evidence_level"] == "cold_start"
    assert "Horror films" in serialized["ranking_expectation"]["reason"]
    assert serialized["ranking_expectation"]["calculation"].startswith("80%")
    assert serialized["public_rating_prior"] == 3.6429
    assert len(serialized["why_you_may_like_it"]) == 2
    assert serialized["why_you_may_not_like_it"]


def test_bottom_result_explains_negative_fit() -> None:
    catalog = pd.DataFrame(
        {"movieId": [1, 2, 3], "genres": ["Drama", "Horror", "Comedy"], "year": [1980, 1990, 2000]}
    )
    personal = {1: 5.0, 2: 1.0}
    content = ContentBaseline.fit(catalog, personal)
    matrix = sparse.csr_matrix(np.array([[5.0, 1.0, 3.0], [4.0, 2.0, 3.0]]))
    movie_ids = np.array([1, 2, 3])
    popularity = PopularityBaseline.fit(matrix, movie_ids)
    collaborative = LatentFactorModel.fit(matrix, movie_ids, factors=1)
    ranked = rank_current_candidates(
        [
            {
                "id": 20,
                "title": "Risky Horror",
                "release_date": "1990-01-01",
                "genre_ids": [27],
                "vote_average": 5.0,
                "vote_count": 100,
            }
        ],
        excluded_tmdb_ids=set(),
        movielens_by_tmdb={20: 2},
        content=content,
        collaborative=collaborative,
        personal_factors=collaborative.fit_personal(personal),
        popularity=popularity,
        user_mean=3.0,
        descending=False,
    )[0].to_dict()

    assert ranked["why_you_may_not_like_it"]
    assert "rate horror films lower" in ranked["why_you_may_not_like_it"][0]


def test_catalog_preselection_honors_year_and_exclusions() -> None:
    catalog = pd.DataFrame(
        {
            "movieId": [1, 2, 3],
            "tmdb_id": [10, 20, 30],
            "genres": ["Drama", "Horror", "Comedy"],
            "year": [1980, 2000, 2020],
        }
    )
    personal = {1: 2.0, 2: 5.0}
    content = ContentBaseline.fit(catalog, personal)
    matrix = sparse.csr_matrix(np.array([[2.0, 5.0, 3.0], [3.0, 4.5, 3.5]]))
    movie_ids = np.array([1, 2, 3])
    popularity = PopularityBaseline.fit(matrix, movie_ids)
    collaborative = LatentFactorModel.fit(matrix, movie_ids, factors=1)

    selected = preselect_movielens_candidates(
        catalog,
        excluded_tmdb_ids={20},
        content=content,
        collaborative=collaborative,
        personal_factors=collaborative.fit_personal(personal),
        popularity=popularity,
        minimum_ratings=1,
        year_min=1990,
    )

    assert selected == [30]


def test_popularity_categories_separate_reach_from_quality() -> None:
    assert classify_popularity(2020, 20_000) == "blockbuster"
    assert classify_popularity(2020, 5_000) == "popular"
    assert classify_popularity(1990, 500) == "cult_classic"
    assert classify_popularity(2026, 500) == "under_the_radar"
    assert classify_popularity(2026, 5) == "unknown"


def test_metadata_matches_are_explained_as_natural_language() -> None:
    reason = humanize_metadata_matches(
        ("story/theme: friendship", "release era: 1990s", "genre: drama")
    )

    assert reason == "stories involving friendship, films from the 1990s, and drama films"


def test_caution_matches_are_clear_and_natural() -> None:
    reason = humanize_caution_matches(
        ("genre: drama", "story/theme: 1940s", "original language: fr")
    )

    assert reason == (
        "you have tended to rate drama films lower, period stories set in the 1940s have "
        "been less reliable for you, and French-language films have been less predictable "
        "matches for you"
    )
