from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd
import typer

from app.db.session import SessionLocal
from app.services.personal_ratings import linked_personal_ratings
from ml.artifacts.movielens import load_movielens_artifacts
from recommendation.baselines.content import ContentBaseline
from recommendation.baselines.popularity import PopularityBaseline


def main(artifact_dir: Path, user: str = "default") -> None:
    matrix, _, movie_ids, source_manifest = load_movielens_artifacts(artifact_dir)
    catalog = pd.read_csv(artifact_dir / source_manifest["files"]["catalog"])
    model_dir = artifact_dir / "baselines" / user
    popularity = PopularityBaseline.fit(matrix, movie_ids)
    popularity.save(model_dir)
    with SessionLocal() as session:
        try:
            personal = linked_personal_ratings(session, user, catalog)
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
    content_status: dict[str, object]
    if len(personal) >= 2:
        content = ContentBaseline.fit(catalog, personal)
        content_scores = content.predict_catalog(catalog)
        model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(content, model_dir / "content.joblib")
        pd.DataFrame(
            {"movieId": catalog["movieId"].astype(int), "predicted_rating": content_scores}
        ).to_csv(model_dir / "content_scores.csv.gz", index=False, compression="gzip")
        content_status = {"status": "trained", "personal_ratings": len(personal)}
    else:
        content_status = {
            "status": "skipped",
            "personal_ratings": len(personal),
            "reason": "At least two TMDB-to-MovieLens-linked personal ratings are required",
        }
    manifest = {
        "trained_at": datetime.now(UTC).isoformat(),
        "source_artifact_version": source_manifest["version"],
        "user": user,
        "popularity": {
            "status": "trained",
            "global_mean": popularity.global_mean,
            "shrinkage": popularity.shrinkage,
        },
        "content": content_status,
    }
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    typer.echo(json.dumps({"model_dir": str(model_dir), **manifest}, indent=2))


if __name__ == "__main__":
    typer.run(main)
