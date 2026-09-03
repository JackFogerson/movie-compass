from __future__ import annotations

import json

import pandas as pd
import typer
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import User
from app.db.session import SessionLocal
from app.services.local_catalog_mapping import map_pending_from_local_catalog
from app.services.recommendation_reports import _latest_artifact


def main(user: str) -> None:
    settings = get_settings()
    artifact = _latest_artifact(settings.ml_artifacts_dir)
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    catalog = pd.read_csv(artifact / manifest["files"]["catalog"])
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.slug == user))
        if owner is None:
            raise typer.BadParameter(f"Unknown user: {user}")
        result = map_pending_from_local_catalog(
            session,
            owner.id,
            catalog,
            settings.processed_data_dir / "tmdb-rich-details.json",
        )
    typer.echo(json.dumps(result.__dict__, indent=2))


if __name__ == "__main__":
    typer.run(main)
