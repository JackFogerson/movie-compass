import numpy as np

from ml.evaluation.ranking import compute_ranking_metrics
from recommendation.baselines.popularity import PopularityBaseline
from recommendation.ranking.current_catalog import RankedMovie


def _movie(
    rank: int,
    movie_id: int | None,
    year: int,
    genres: tuple[str, ...],
    mode: str,
) -> RankedMovie:
    return RankedMovie(
        rank=rank,
        tmdb_id=rank,
        movielens_id=movie_id,
        title=f"Movie {rank}",
        release_date=f"{year}-01-01",
        year=year,
        genres=genres,
        runtime=100,
        score=4.0,
        score_mode=mode,
        candidate_origin="movielens_catalog" if movie_id else "tmdb_recent",
        content_score=4.0,
        content_model="tmdb_metadata",
        collaborative_score=4.0 if movie_id else None,
        popularity_score=4.0 if movie_id else None,
        popularity_tier="popular",
        audience_evidence_count=100,
        tmdb_vote_average=8.0,
        tmdb_vote_count=100,
        review_theme_affinity=None,
        explanation=(),
    )


def test_ranking_metrics_measure_coverage_diversity_and_novelty() -> None:
    popularity = PopularityBaseline(
        movie_ids=np.array([10, 20]),
        scores=np.array([4.0, 3.5]),
        counts=np.array([100, 10]),
        global_mean=3.5,
        shrinkage=25.0,
    )
    recommendations = [
        _movie(1, 10, 1985, ("Drama", "War"), "hybrid"),
        _movie(2, None, 2025, ("Comedy",), "cold_start"),
    ]

    metrics = compute_ranking_metrics(
        recommendations,
        candidates_considered=10,
        popularity=popularity,
        total_users=1000,
    )

    assert metrics["coverage"]["selection_rate"] == 0.2
    assert metrics["coverage"]["movielens_evidence"] == 1
    assert metrics["diversity"]["distinct_decades"] == 2
    assert metrics["diversity"]["intra_list_genre_diversity"] == 1.0
    assert metrics["novelty"]["movielens_items_measured"] == 1
