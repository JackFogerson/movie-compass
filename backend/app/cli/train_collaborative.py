import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import typer

from ml.artifacts.movielens import load_movielens_artifacts
from recommendation.collaborative.latent_factor import LatentFactorModel


def main(
    artifact_dir: Path,
    factors: int = 64,
    random_state: int = 42,
) -> None:
    ratings, _, movie_ids, source_manifest = load_movielens_artifacts(artifact_dir)
    model = LatentFactorModel.fit(ratings, movie_ids, factors=factors, random_state=random_state)
    model_dir = artifact_dir / "collaborative"
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_dir / "latent_factor.joblib")
    manifest = {
        "model": "truncated_svd_explicit_residual",
        "trained_at": datetime.now(UTC).isoformat(),
        "source_artifact_version": source_manifest["version"],
        "requested_factors": factors,
        "effective_factors": model.factors,
        "random_state": random_state,
        "explained_variance": model.explained_variance,
        "artifact": "latent_factor.joblib",
    }
    (model_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    typer.echo(json.dumps({"model_dir": str(model_dir), **manifest}, indent=2))


if __name__ == "__main__":
    typer.run(main)
