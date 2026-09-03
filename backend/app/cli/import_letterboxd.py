import json
from pathlib import Path

import typer

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.letterboxd_import import import_letterboxd_archive
from app.services.tmdb_mapping import map_pending_letterboxd
from ingestion.letterboxd.parser import parse_export
from ingestion.tmdb.client import TmdbClient


def main(
    archive: Path,
    report_path: Path | None = None,
    user: str = "default",
    persist: bool = True,
    map_tmdb: bool = False,
    mapping_limit: int = 100,
    force: bool = False,
    retry_unresolved: bool = False,
) -> None:
    movies, report = parse_export(archive)
    payload = {"report": report.__dict__, "movies": [movie.to_dict() for movie in movies]}
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    output: dict = {"parsed": report.__dict__}
    if persist:
        with SessionLocal() as session:
            persisted = import_letterboxd_archive(session, archive, user, force=force)
            output["persistence"] = persisted.__dict__
            if map_tmdb:
                settings = get_settings()
                if not settings.tmdb_api_key:
                    raise typer.BadParameter("TMDB_API_KEY is required with --map-tmdb")
                client = TmdbClient(settings.tmdb_api_key)
                try:
                    mapped = map_pending_letterboxd(
                        session,
                        client,
                        persisted.user_id,
                        limit=mapping_limit,
                        ttl_seconds=settings.tmdb_cache_ttl_seconds,
                        retry_unresolved=retry_unresolved,
                    )
                    output["mapping"] = mapped.__dict__
                finally:
                    client.close()
    typer.echo(json.dumps(output, indent=2))


if __name__ == "__main__":
    typer.run(main)
