from __future__ import annotations

import json

import typer

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.personal_ratings import personal_tmdb_ratings
from ml.evaluation.tmdb_content import evaluate_tmdb_content


def main(user: str = "default", alpha: float = 0.5) -> None:
    settings = get_settings()
    cache_path = settings.processed_data_dir / "tmdb-rich-details.json"
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    details = {int(key): value for key, value in cached.items()}
    with SessionLocal() as session:
        ratings = personal_tmdb_ratings(session, user)
    evaluation = evaluate_tmdb_content(details, ratings, alpha=alpha)
    print(json.dumps({"alpha": alpha, **evaluation.__dict__}, indent=2))


if __name__ == "__main__":
    typer.run(main)
