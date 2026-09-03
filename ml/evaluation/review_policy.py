from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from ml.evaluation.review_themes import evaluate_review_themes


@dataclass(frozen=True)
class ReviewSignalPolicy:
    evaluated_at: str
    usable_reviewed_ratings: int
    enabled: bool
    selected_scale: float
    baseline_mae: float | None
    baseline_rmse: float | None
    selected_mae: float | None
    selected_rmse: float | None
    minimum_mae_improvement: float
    tested: tuple[dict, ...]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_review_policy(
    details_by_id: dict[int, dict],
    ratings_by_id: dict[int, float],
    reviews_by_id: dict[int, str],
    *,
    scales: tuple[float, ...] = (0.1, 0.25, 0.5, 0.75, 1.0),
    minimum_mae_improvement: float = 0.01,
) -> ReviewSignalPolicy:
    usable = len(set(details_by_id).intersection(ratings_by_id, reviews_by_id))
    if usable < 15:
        return ReviewSignalPolicy(
            datetime.now(UTC).isoformat(),
            usable,
            False,
            0.0,
            None,
            None,
            None,
            None,
            minimum_mae_improvement,
            (),
            "At least fifteen enriched, rated movies with reviews are required.",
        )
    tested = []
    evaluations = []
    for scale in scales:
        result = evaluate_review_themes(
            details_by_id,
            ratings_by_id,
            reviews_by_id,
            scale=scale,
        )
        evaluations.append(result)
        tested.append(
            {
                "scale": scale,
                "mae": result.combined_mae,
                "rmse": result.combined_rmse,
            }
        )
    best = min(evaluations, key=lambda item: (item.combined_mae, item.combined_rmse))
    mae_improvement = best.rich_content_mae - best.combined_mae
    enabled = (
        mae_improvement >= minimum_mae_improvement
        and best.combined_rmse <= best.rich_content_rmse
    )
    reason = (
        "Review themes improved held-out MAE and did not worsen RMSE for this profile."
        if enabled
        else "Review themes did not improve held-out accuracy for this profile."
    )
    return ReviewSignalPolicy(
        datetime.now(UTC).isoformat(),
        usable,
        enabled,
        best.scale if enabled else 0.0,
        best.rich_content_mae,
        best.rich_content_rmse,
        best.combined_mae,
        best.combined_rmse,
        minimum_mae_improvement,
        tuple(tested),
        reason,
    )
