from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

TITLE_YEAR = re.compile(r"^(?P<title>.*) \((?P<year>\d{4})\)$")


@dataclass(frozen=True)
class MovieLensStats:
    movies: int
    ratings: int
    users: int
    linked_to_tmdb: int
    linked_to_imdb: int


def load_movies(dataset_dir: Path) -> pd.DataFrame:
    movies = pd.read_csv(
        dataset_dir / "movies.csv",
        dtype={"movieId": "int64", "title": "string", "genres": "string"},
    )
    parsed = movies["title"].str.extract(TITLE_YEAR)
    movies["clean_title"] = parsed["title"].fillna(movies["title"]).str.strip()
    movies["year"] = pd.to_numeric(parsed["year"], errors="coerce").astype("Int64")
    movies["genre_list"] = (
        movies["genres"]
        .fillna("")
        .map(lambda value: [] if value == "(no genres listed)" else value.split("|"))
    )
    return movies


def load_links(dataset_dir: Path) -> pd.DataFrame:
    links = pd.read_csv(
        dataset_dir / "links.csv",
        dtype={"movieId": "int64", "imdbId": "string", "tmdbId": "string"},
    )
    links["imdb_id"] = links["imdbId"].map(
        lambda value: f"tt{int(value):07d}" if pd.notna(value) and value else pd.NA
    )
    links["tmdb_id"] = pd.to_numeric(links["tmdbId"], errors="coerce").astype("Int64")
    return links[["movieId", "imdb_id", "tmdb_id"]]


def iter_ratings(dataset_dir: Path, chunksize: int = 1_000_000):
    yield from pd.read_csv(
        dataset_dir / "ratings.csv",
        dtype={"userId": "int32", "movieId": "int32", "rating": "float32", "timestamp": "int64"},
        chunksize=chunksize,
    )


def build_movie_catalog(dataset_dir: Path) -> pd.DataFrame:
    return load_movies(dataset_dir).merge(
        load_links(dataset_dir), on="movieId", how="left", validate="one_to_one"
    )


def collect_stats(dataset_dir: Path) -> MovieLensStats:
    catalog = build_movie_catalog(dataset_dir)
    rating_count = 0
    users: set[int] = set()
    for chunk in iter_ratings(dataset_dir):
        rating_count += len(chunk)
        users.update(chunk["userId"].unique().tolist())
    return MovieLensStats(
        len(catalog),
        rating_count,
        len(users),
        int(catalog["tmdb_id"].notna().sum()),
        int(catalog["imdb_id"].notna().sum()),
    )


def write_processed_catalog(dataset_dir: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "movielens_movies.csv.gz"
    catalog = build_movie_catalog(dataset_dir).drop(columns=["genre_list"])
    catalog.to_csv(target, index=False, compression="gzip")
    return target
