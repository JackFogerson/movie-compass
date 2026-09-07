from __future__ import annotations

import json
from pathlib import Path

from app.db.session import SessionLocal
from app.services.personal_ratings import personal_tmdb_ratings, personal_tmdb_reviews
from ml.evaluation.review_policy import evaluate_review_policy


def refresh_review_policy(user: str, details_cache: Path, output: Path) -> dict:
    try:
        cached = (
            json.loads(details_cache.read_text(encoding="utf-8"))
            if details_cache.is_file()
            else {}
        )
    except (OSError, json.JSONDecodeError):
        cached = {}
    details = {
        int(key): value
        for key, value in cached.items()
        if value.get("missing") is not True
    }
    with SessionLocal() as session:
        ratings = personal_tmdb_ratings(session, user)
        reviews = personal_tmdb_reviews(session, user)
    policy = evaluate_review_policy(details, ratings, reviews)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(policy.to_dict(), indent=2), encoding="utf-8")
    return policy.to_dict()


def load_review_policy(path: Path) -> dict:
    if not path.is_file():
        return {
            "enabled": False,
            "selected_scale": 0.0,
            "reason": "Review policy has not been evaluated for this profile.",
        }
    return json.loads(path.read_text(encoding="utf-8"))
