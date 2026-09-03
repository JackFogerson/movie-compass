from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import typer
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import ImportMapping, User
from app.db.session import SessionLocal
from app.services.mapping_enrichment import enrich_ambiguous_mapping
from ingestion.tmdb.client import TmdbClient


def main(
    user: str = "default",
    output: Path = Path("data/processed/ambiguous-mappings.json"),
) -> None:
    settings = get_settings()
    if not settings.tmdb_api_key:
        raise typer.BadParameter("TMDB_API_KEY is required")
    client = TmdbClient(settings.tmdb_api_key)
    try:
        with SessionLocal() as session:
            owner = session.scalar(select(User).where(User.slug == user))
            if owner is None:
                raise typer.BadParameter(f"Unknown user: {user}")
            mapping_ids = session.scalars(
                select(ImportMapping.id).where(
                    ImportMapping.user_id == owner.id,
                    ImportMapping.status == "ambiguous",
                )
            ).all()
            report = [
                asdict(enrich_ambiguous_mapping(session, client, mapping_id))
                for mapping_id in mapping_ids
            ]
    finally:
        client.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    typer.echo(json.dumps({"output": str(output), "mappings": len(report)}, indent=2))


if __name__ == "__main__":
    typer.run(main)
