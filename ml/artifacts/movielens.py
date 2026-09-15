from __future__ import annotations

import gc
import hashlib
import json
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scipy import sparse

from ingestion.movielens.parser import build_movie_catalog, iter_ratings


@dataclass(frozen=True)
class MovieLensArtifactManifest:
    version: str
    created_at: str
    dataset_name: str
    ratings: int
    users: int
    movies: int
    matrix_shape: tuple[int, int]
    matrix_nnz: int
    source_sha256: dict[str, str]
    files: dict[str, str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_hashes(dataset_dir: Path) -> dict[str, str]:
    return {
        name: _sha256(dataset_dir / name)
        for name in ("movies.csv", "links.csv", "ratings.csv")
    }


def build_movielens_artifacts(
    dataset_dir: Path, output_root: Path, *, chunksize: int = 1_000_000
) -> tuple[Path, MovieLensArtifactManifest]:
    catalog = build_movie_catalog(dataset_dir).sort_values("movieId").reset_index(drop=True)
    movie_ids = catalog["movieId"].to_numpy(dtype=np.int64)
    user_ids_seen: set[int] = set()
    rating_count = 0
    for chunk in iter_ratings(dataset_dir, chunksize):
        user_ids_seen.update(int(value) for value in chunk["userId"].unique())
        rating_count += len(chunk)
    user_ids = np.array(sorted(user_ids_seen), dtype=np.int64)
    source_hashes = _source_hashes(dataset_dir)
    version_input = json.dumps(source_hashes, sort_keys=True).encode()
    version = hashlib.sha256(version_input).hexdigest()[:12]
    artifact_dir = output_root / f"movielens-32m-{version}"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=artifact_dir) as temporary:
        temp_dir = Path(temporary)
        rows = np.lib.format.open_memmap(
            temp_dir / "rows.npy", mode="w+", dtype=np.int32, shape=(rating_count,)
        )
        columns = np.lib.format.open_memmap(
            temp_dir / "columns.npy", mode="w+", dtype=np.int32, shape=(rating_count,)
        )
        values = np.lib.format.open_memmap(
            temp_dir / "values.npy", mode="w+", dtype=np.float32, shape=(rating_count,)
        )
        offset = 0
        for chunk in iter_ratings(dataset_dir, chunksize):
            end = offset + len(chunk)
            rows[offset:end] = np.searchsorted(
                user_ids, chunk["userId"].to_numpy(dtype=np.int64)
            )
            columns[offset:end] = np.searchsorted(
                movie_ids, chunk["movieId"].to_numpy(dtype=np.int64)
            )
            values[offset:end] = chunk["rating"].to_numpy(dtype=np.float32)
            offset = end
        coordinate_matrix = sparse.coo_matrix(
            (values, (rows, columns)), shape=(len(user_ids), len(movie_ids))
        )
        matrix = coordinate_matrix.tocsr(copy=True)
        rows.flush()
        columns.flush()
        values.flush()
        del coordinate_matrix, rows, columns, values
        gc.collect()

    matrix_path = artifact_dir / "ratings_csr.npz"
    user_path = artifact_dir / "user_ids.npy"
    movie_path = artifact_dir / "movie_ids.npy"
    catalog_path = artifact_dir / "catalog.csv.gz"
    sparse.save_npz(matrix_path, matrix, compressed=True)
    np.save(user_path, user_ids)
    np.save(movie_path, movie_ids)
    catalog.drop(columns=["genre_list"]).to_csv(
        catalog_path, index=False, compression="gzip"
    )
    manifest = MovieLensArtifactManifest(
        version=version,
        created_at=datetime.now(UTC).isoformat(),
        dataset_name="MovieLens 32M",
        ratings=rating_count,
        users=len(user_ids),
        movies=len(movie_ids),
        matrix_shape=matrix.shape,
        matrix_nnz=matrix.nnz,
        source_sha256=source_hashes,
        files={
            "ratings": matrix_path.name,
            "user_ids": user_path.name,
            "movie_ids": movie_path.name,
            "catalog": catalog_path.name,
        },
    )
    (artifact_dir / "manifest.json").write_text(
        json.dumps(asdict(manifest), indent=2), encoding="utf-8"
    )
    return artifact_dir, manifest


def load_movielens_artifacts(
    artifact_dir: Path,
) -> tuple[sparse.csr_matrix, np.ndarray, np.ndarray, dict]:
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    matrix = sparse.load_npz(artifact_dir / manifest["files"]["ratings"]).tocsr()
    user_ids = np.load(artifact_dir / manifest["files"]["user_ids"])
    movie_ids = np.load(artifact_dir / manifest["files"]["movie_ids"])
    return matrix, user_ids, movie_ids, manifest
