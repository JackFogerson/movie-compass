from __future__ import annotations

import json

import typer

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.personal_ratings import personal_tmdb_ratings, personal_tmdb_reviews
from ml.evaluation.review_themes import evaluate_review_themes


def main(user: str = "default", scale: float = 0.5) -> None:
    cache_path = get_settings().processed_data_dir / "tmdb-rich-details.json"
    details = {
        int(key): value
        for key, value in json.loads(cache_path.read_text(encoding="utf-8")).items()
        if value.get("missing") is not True
    }
    with SessionLocal() as session:
        ratings = personal_tmdb_ratings(session, user)
        reviews = personal_tmdb_reviews(session, user)
    evaluation = evaluate_review_themes(details, ratings, reviews, scale=scale)
    typer.echo(json.dumps(evaluation.__dict__, indent=2))


if __name__ == "__main__":
    typer.run(main)
