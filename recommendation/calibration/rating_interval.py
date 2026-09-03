from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class RatingInterval:
    lower_offset: float
    upper_offset: float
    coverage: float
    samples: int
    method: str

    @classmethod
    def from_evaluations(
        cls,
        directory: Path,
        *,
        model: str = "hybrid",
        coverage: float = 0.90,
    ) -> RatingInterval:
        residuals: list[float] = []
        for path in sorted(directory.glob("heldout-seed-*.json")):
            report = json.loads(path.read_text(encoding="utf-8"))
            residuals.extend(
                float(row["actual"]) - float(row[model])
                for row in report.get("errors", [])
                if model in row and row.get("actual") is not None
            )
        if len(residuals) < 20:
            return cls(-1.25, 1.25, coverage, len(residuals), "conservative_fallback")
        tail = (1.0 - coverage) / 2.0
        return cls(
            lower_offset=float(np.quantile(residuals, tail)),
            upper_offset=float(np.quantile(residuals, 1.0 - tail)),
            coverage=coverage,
            samples=len(residuals),
            method="heldout_residual_quantiles",
        )

    def apply(self, expected_rating: float) -> tuple[float, float]:
        return (
            round(float(np.clip(expected_rating + self.lower_offset, 0.5, 5.0)), 2),
            round(float(np.clip(expected_rating + self.upper_offset, 0.5, 5.0)), 2),
        )
