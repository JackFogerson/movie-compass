from pathlib import Path

from ingestion.movielens.parser import build_movie_catalog, collect_stats, load_movies


def _dataset(path: Path) -> None:
    path.mkdir()
    (path / "movies.csv").write_text(
        "movieId,title,genres\n1,Toy Story (1995),Adventure|Animation\n2,No Year,Drama\n",
        encoding="utf-8",
    )
    (path / "links.csv").write_text("movieId,imdbId,tmdbId\n1,114709,862\n2,,\n", encoding="utf-8")
    (path / "ratings.csv").write_text(
        "userId,movieId,rating,timestamp\n1,1,4.0,1\n2,1,5.0,2\n", encoding="utf-8"
    )


def test_load_and_link_catalog(tmp_path: Path) -> None:
    dataset = tmp_path / "ml-32m"
    _dataset(dataset)
    movies = load_movies(dataset)
    assert movies.loc[0, "clean_title"] == "Toy Story"
    assert movies.loc[0, "year"] == 1995
    catalog = build_movie_catalog(dataset)
    assert catalog.loc[0, "tmdb_id"] == 862
    assert catalog.loc[0, "imdb_id"] == "tt0114709"


def test_collect_stats_streams_ratings(tmp_path: Path) -> None:
    dataset = tmp_path / "ml-32m"
    _dataset(dataset)
    stats = collect_stats(dataset)
    assert (stats.movies, stats.ratings, stats.users, stats.linked_to_tmdb) == (2, 2, 2, 1)
