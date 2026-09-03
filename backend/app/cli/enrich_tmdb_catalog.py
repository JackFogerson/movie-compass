from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import typer

from app.core.config import get_settings
from ingestion.tmdb.client import TmdbClient
from ingestion.tmdb.details_cache import load_or_fetch_details
from ml.artifacts.movielens import load_movielens_artifacts


def _latest_artifact(root: Path) -> Path:
    candidates = [
        path
        for path in root.glob("movielens-32m-*")
        if path.is_dir() and (path / "manifest.json").is_file()
    ]
    if not candidates:
        raise typer.BadParameter("No MovieLens artifact is available")
    return max(candidates, key=lambda path: (path / "manifest.json").stat().st_mtime)


def main(limit: int = 100) -> None:
    if limit < 1 or limit > 2_000:
        raise typer.BadParameter("limit must be between 1 and 2000")
    settings = get_settings()
    if not settings.tmdb_api_key:
        raise typer.BadParameter("TMDB_API_KEY is required")
    database = settings.processed_data_dir / "tmdb-catalog.sqlite3"
    if not database.is_file():
        raise typer.BadParameter("Run sync_tmdb_catalog first")
    artifact = _latest_artifact(settings.ml_artifacts_dir)
    _, _, _, manifest = load_movielens_artifacts(artifact)
    catalog = pd.read_csv(artifact / manifest["files"]["catalog"])
    covered = {int(value) for value in catalog["tmdb_id"].dropna()}
    cache_path = settings.processed_data_dir / "tmdb-rich-details.json"
    cached = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    covered.update(int(value) for value in cached)

    selected: list[int] = []
    with sqlite3.connect(database) as connection:
        cursor = connection.execute(
            "SELECT tmdb_id FROM movies WHERE adult = 0 AND video = 0 "
            "ORDER BY popularity DESC"
        )
        for (tmdb_id,) in cursor:
            if int(tmdb_id) in covered:
                continue
            selected.append(int(tmdb_id))
            if len(selected) >= limit:
                break

    client = TmdbClient(settings.tmdb_api_key)
    try:
        available, fetched = load_or_fetch_details(client, set(selected), cache_path)
    finally:
        client.close()
    typer.echo(
        json.dumps(
            {
                "requested": limit,
                "selected": len(selected),
                "details_fetched": fetched,
                "rankable_added": len(available),
                "cache_total": len(cached) + len(available),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    typer.run(main)
