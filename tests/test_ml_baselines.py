from pathlib import Path

import numpy as np
import pandas as pd

from ml.artifacts.movielens import build_movielens_artifacts, load_movielens_artifacts
from recommendation.baselines.content import ContentBaseline
from recommendation.baselines.popularity import PopularityBaseline


def _dataset(path: Path) -> None:
    path.mkdir()
    (path / "movies.csv").write_text(
        "movieId,title,genres\n"
        "1,Space One (2000),Sci-Fi|Drama\n"
        "2,Comedy One (2001),Comedy\n"
        "3,Space Two (2010),Sci-Fi|Drama\n",
        encoding="utf-8",
    )
    (path / "links.csv").write_text(
        "movieId,imdbId,tmdbId\n1,1,101\n2,2,102\n3,3,103\n", encoding="utf-8"
    )
    (path / "ratings.csv").write_text(
        "userId,movieId,rating,timestamp\n10,1,5.0,1\n10,2,2.0,2\n20,1,4.0,3\n20,3,5.0,4\n",
        encoding="utf-8",
    )


def test_artifacts_are_sparse_versioned_and_loadable(tmp_path: Path) -> None:
    dataset = tmp_path / "ml-32m"
    _dataset(dataset)
    artifact_dir, manifest = build_movielens_artifacts(dataset, tmp_path / "artifacts", chunksize=2)
    matrix, users, movies, loaded = load_movielens_artifacts(artifact_dir)
    assert matrix.shape == (2, 3)
    assert matrix.nnz == 4
    assert users.tolist() == [10, 20]
    assert movies.tolist() == [1, 2, 3]
    assert loaded["version"] == manifest.version


def test_popularity_and_content_baselines_make_real_predictions() -> None:
    from scipy import sparse

    ratings = sparse.csr_matrix([[5.0, 2.0, 0.0], [4.0, 0.0, 5.0]])
    popularity = PopularityBaseline.fit(ratings, np.array([1, 2, 3]), shrinkage=1.0)
    assert popularity.predict(1) > popularity.predict(2)
    catalog = pd.DataFrame(
        {
            "movieId": [1, 2, 3],
            "genres": ["Sci-Fi|Drama", "Comedy", "Sci-Fi|Drama"],
            "year": [2000, 2001, 2010],
        }
    )
    content = ContentBaseline.fit(catalog, {1: 5.0, 2: 1.0})
    predictions = content.predict_catalog(catalog)
    assert predictions.shape == (3,)
    assert np.all((predictions >= 0.5) & (predictions <= 5.0))
