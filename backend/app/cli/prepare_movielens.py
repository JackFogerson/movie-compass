import json
from pathlib import Path

import typer

from app.core.config import get_settings
from ml.artifacts.movielens import build_movielens_artifacts


def main(dataset_dir: Path | None = None, output_dir: Path | None = None) -> None:
    settings = get_settings()
    source = dataset_dir or settings.raw_data_dir / "ml-32m"
    target = output_dir or Path("ml/artifacts")
    artifact_dir, manifest = build_movielens_artifacts(source, target)
    typer.echo(
        json.dumps({"artifact_dir": str(artifact_dir), "manifest": manifest.__dict__}, indent=2)
    )


if __name__ == "__main__":
    typer.run(main)
