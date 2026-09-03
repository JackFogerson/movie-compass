import json
from pathlib import Path

from recommendation.calibration.rating_interval import RatingInterval


def test_rating_interval_uses_heldout_residuals_and_clips_scale(tmp_path: Path) -> None:
    errors = [
        {"actual": float((index % 5) + 1), "hybrid": 3.0}
        for index in range(25)
    ]
    (tmp_path / "heldout-seed-1.json").write_text(
        json.dumps({"errors": errors}), encoding="utf-8"
    )

    interval = RatingInterval.from_evaluations(tmp_path, coverage=0.90)
    minimum, maximum = interval.apply(4.5)

    assert interval.method == "heldout_residual_quantiles"
    assert interval.samples == 25
    assert 0.5 <= minimum < maximum <= 5.0
