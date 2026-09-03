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
from ml.evaluation.personal import evaluate_personal_ratings
from recommendation.baselines.popularity import PopularityBaseline
from recommendation.collaborative.latent_factor import LatentFactorModel


def main(
    artifact_dir: Path,
    user: str = "default",
    seed: int = 42,
    test_fraction: float = 0.2,
) -> None:
    matrix, _, movie_ids, source_manifest = load_movielens_artifacts(artifact_dir)
    catalog = pd.read_csv(artifact_dir / source_manifest["files"]["catalog"])
    model_path = artifact_dir / "collaborative" / "latent_factor.joblib"
    if not model_path.exists():
        raise typer.BadParameter(
            f"Collaborative model is missing; run train_collaborative first: {model_path}"
        )
    collaborative: LatentFactorModel = joblib.load(model_path)
    popularity = PopularityBaseline.fit(matrix, movie_ids)
    with SessionLocal() as session:
        try:
            personal = linked_personal_ratings(session, user, catalog)
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
    try:
        evaluation = evaluate_personal_ratings(
            catalog,
            personal,
            popularity,
            collaborative,
            seed=seed,
            test_fraction=test_fraction,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    output = {
        "evaluated_at": datetime.now(UTC).isoformat(),
        "user": user,
        "source_artifact_version": source_manifest["version"],
        **evaluation.to_dict(),
    }
    output_dir = artifact_dir / "evaluations" / user
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"heldout-seed-{seed}.json"
    target.write_text(json.dumps(output, indent=2), encoding="utf-8")
    typer.echo(json.dumps({"report": str(target), **output}, indent=2))


if __name__ == "__main__":
    typer.run(main)
