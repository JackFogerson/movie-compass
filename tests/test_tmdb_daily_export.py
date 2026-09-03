import gzip
import json
import sqlite3
from datetime import date
from pathlib import Path

from ingestion.tmdb.daily_export import build_catalog_index, load_catalog_summary


def test_daily_export_builds_filtered_catalog_index(tmp_path: Path) -> None:
    archive = tmp_path / "movies.json.gz"
    rows = [
        {"id": 1, "popularity": 12.5, "adult": False, "video": False},
        {"id": 2, "popularity": 0, "adult": True, "video": False},
        {"id": 3, "popularity": 2, "adult": False, "video": True},
    ]
    with gzip.open(archive, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    database = tmp_path / "catalog.sqlite3"
    manifest = tmp_path / "manifest.json"

    summary = build_catalog_index(
        archive,
        database,
        export_date=date(2026, 8, 31),
        source_url="https://example.test/movies.json.gz",
        source_sha256="abc",
        manifest_path=manifest,
    )

    with sqlite3.connect(database) as connection:
        indexed = connection.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
    assert indexed == 3
    assert summary.records == 3
    assert summary.eligible_movies == 1
    assert summary.adult_movies_excluded == 1
    assert summary.video_records_excluded == 1
    assert load_catalog_summary(manifest)["maximum_tmdb_id"] == 3
