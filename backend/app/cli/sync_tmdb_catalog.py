from __future__ import annotations

import json
from datetime import date, timedelta

import httpx
import typer

from app.core.config import get_settings
from ingestion.tmdb.daily_export import build_catalog_index, download_daily_export


def main(export_date: str | None = None, fallback_days: int = 3) -> None:
    settings = get_settings()
    try:
        requested = date.fromisoformat(export_date) if export_date else date.today()
    except ValueError as error:
        raise typer.BadParameter("export_date must use YYYY-MM-DD") from error
    last_error: Exception | None = None
    for offset in range(fallback_days):
        candidate_date = requested - timedelta(days=offset)
        archive = settings.raw_data_dir / "tmdb" / f"movie_ids_{candidate_date:%m_%d_%Y}.json.gz"
        try:
            source_url, source_sha256 = download_daily_export(candidate_date, archive)
            summary = build_catalog_index(
                archive,
                settings.processed_data_dir / "tmdb-catalog.sqlite3",
                export_date=candidate_date,
                source_url=source_url,
                source_sha256=source_sha256,
                manifest_path=settings.processed_data_dir / "tmdb-catalog-manifest.json",
            )
            typer.echo(json.dumps(summary.__dict__, indent=2))
            return
        except httpx.HTTPStatusError as error:
            last_error = error
            if error.response.status_code != 404:
                raise
    raise typer.BadParameter(f"No TMDB daily export was available: {last_error}")


if __name__ == "__main__":
    typer.run(main)
