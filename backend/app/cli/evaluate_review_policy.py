from __future__ import annotations

import json

import typer

from app.core.config import get_settings
from app.services.review_policy import refresh_review_policy


def main(user: str) -> None:
    settings = get_settings()
    policy = refresh_review_policy(
        user,
        settings.processed_data_dir / "tmdb-rich-details.json",
        settings.processed_data_dir / "review-policies" / f"{user}.json",
    )
    typer.echo(json.dumps(policy, indent=2))


if __name__ == "__main__":
    typer.run(main)
