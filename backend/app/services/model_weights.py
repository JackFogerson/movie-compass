from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from threading import Lock

import numpy as np
import pandas as pd

from ml.evaluation.personal import evaluate_personal_ratings
from recommendation.baselines.popularity import PopularityBaseline
from recommendation.baselines.tmdb_content import TmdbContentModel
from recommendation.collaborative.latent_factor import LatentFactorModel
from recommendation.ranking.hybrid import HybridWeights

_LOCK = Lock()
_DEFAULT = HybridWeights()
_SEEDS = (1, 7, 21, 42, 84)
_POLICY_VERSION = 2


def _fingerprint(ratings: dict[int, float]) -> str:
    raw = json.dumps(sorted((int(key), round(value, 3)) for key, value in ratings.items()))
    return hashlib.sha256(raw.encode()).hexdigest()


def _weight_grid(step: int = 5):
    for collaborative in range(0, 101, step):
        for content in range(0, 101 - collaborative, step):
            popularity = 100 - collaborative - content
            yield np.array([collaborative, content, popularity], dtype=float) / 100.0


def select_personalized_weights(
    output_path: Path,
    catalog: pd.DataFrame,
    ratings: dict[int, float],
    popularity: PopularityBaseline,
    collaborative: LatentFactorModel,
    *,
    tmdb_details: dict[int, dict] | None = None,
    tmdb_ratings: dict[int, float] | None = None,
) -> dict:
    """Select stable profile weights from repeated held-out predictions."""
    tmdb_details = tmdb_details or {}
    tmdb_ratings = tmdb_ratings or {}
    tmdb_ids = sorted(set(tmdb_details).intersection(tmdb_ratings))
    fingerprint = _fingerprint(ratings) + ":" + _fingerprint(
        {tmdb_id: tmdb_ratings[tmdb_id] for tmdb_id in tmdb_ids}
    )
    with _LOCK:
        if output_path.is_file():
            try:
                saved = json.loads(output_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                saved = {}
            if (
                saved.get("policy_version") == _POLICY_VERSION
                and saved.get("ratings_fingerprint") == fingerprint
            ):
                return saved

    if len(ratings) < 8:
        selected = _DEFAULT.normalized()
        best = selected
        samples = 0
        default_rmse = None
        selected_rmse = None
        evidence = "insufficient"
    else:
        evaluations = [
            evaluate_personal_ratings(
                catalog,
                ratings,
                popularity,
                collaborative,
                seed=seed,
                minimum_ratings=8,
            )
            for seed in _SEEDS
        ]
        rows = [row for item in evaluations for row in item.errors]
        actual = np.array([float(row["actual"]) for row in rows])
        signals = np.array(
            [
                [float(row["collaborative"]), float(row["content"]), float(row["popularity"])]
                for row in rows
            ]
        )
        default = _DEFAULT.normalized()

        def rmse(weights: np.ndarray) -> float:
            return float(np.sqrt(np.mean((signals @ weights - actual) ** 2)))

        best = min(_weight_grid(), key=rmse)
        # Small profiles retain more of the robust default to avoid tuning to a
        # handful of lucky or unlucky held-out movies.
        evidence_strength = min(0.8, max(0.15, (len(ratings) - 5) / 50.0))
        selected = default * (1.0 - evidence_strength) + best * evidence_strength
        selected /= selected.sum()
        samples = len(rows)
        default_rmse = round(rmse(default), 3)
        selected_rmse = round(rmse(selected), 3)
        evidence = "strong" if len(ratings) >= 50 else "useful" if len(ratings) >= 20 else "early"

    cold_default = np.array([0.8, 0.2], dtype=float)
    cold_best = cold_default
    cold_selected = cold_default
    cold_samples = 0
    cold_default_rmse = None
    cold_selected_rmse = None
    if len(tmdb_ids) >= 10:
        cold_rows = []
        for seed in _SEEDS:
            shuffled = tmdb_ids.copy()
            Random(seed).shuffle(shuffled)
            test_size = max(2, round(len(shuffled) * 0.2))
            test_ids = shuffled[:test_size]
            train_ids = shuffled[test_size:]
            train_ratings = {tmdb_id: tmdb_ratings[tmdb_id] for tmdb_id in train_ids}
            model = TmdbContentModel.fit(tmdb_details, train_ratings)
            metadata = model.predict({tmdb_id: tmdb_details[tmdb_id] for tmdb_id in test_ids})
            for tmdb_id in test_ids:
                item = tmdb_details[tmdb_id]
                reliability = float(item.get("vote_count") or 0)
                reliability /= reliability + 250.0
                public = float(item.get("vote_average") or model.user_mean * 2) / 2.0
                prior = reliability * public + (1.0 - reliability) * model.user_mean
                cold_rows.append((tmdb_ratings[tmdb_id], metadata[tmdb_id], prior))
        actual = np.array([row[0] for row in cold_rows])
        signals = np.array([[row[1], row[2]] for row in cold_rows])

        def cold_rmse(weights: np.ndarray) -> float:
            return float(np.sqrt(np.mean((signals @ weights - actual) ** 2)))

        cold_best = min(
            (np.array([metadata, 100 - metadata], dtype=float) / 100 for metadata in range(101)),
            key=cold_rmse,
        )
        cold_strength = min(0.8, max(0.15, (len(tmdb_ids) - 5) / 50.0))
        cold_selected = cold_default * (1.0 - cold_strength) + cold_best * cold_strength
        cold_selected /= cold_selected.sum()
        cold_samples = len(cold_rows)
        cold_default_rmse = round(cold_rmse(cold_default), 3)
        cold_selected_rmse = round(cold_rmse(cold_selected), 3)

    result = {
        "policy_version": _POLICY_VERSION,
        "selected_at": datetime.now(UTC).isoformat(),
        "ratings_fingerprint": fingerprint,
        "ratings_used": len(ratings),
        "heldout_predictions": samples,
        "evidence": evidence,
        "weights": {
            "collaborative": round(float(selected[0]), 4),
            "content": round(float(selected[1]), 4),
            "popularity": round(float(selected[2]), 4),
        },
        "raw_best_weights": {
            "collaborative": round(float(best[0]), 4),
            "content": round(float(best[1]), 4),
            "popularity": round(float(best[2]), 4),
        },
        "default_rmse": default_rmse,
        "selected_rmse": selected_rmse,
        "cold_start_weights": {
            "metadata": round(float(cold_selected[0]), 4),
            "public_rating": round(float(cold_selected[1]), 4),
        },
        "cold_start_raw_best_weights": {
            "metadata": round(float(cold_best[0]), 4),
            "public_rating": round(float(cold_best[1]), 4),
        },
        "cold_start_ratings_used": len(tmdb_ids),
        "cold_start_heldout_predictions": cold_samples,
        "cold_start_default_rmse": cold_default_rmse,
        "cold_start_selected_rmse": cold_selected_rmse,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def weights_from_policy(policy: dict) -> HybridWeights:
    values = policy["weights"]
    return HybridWeights(
        collaborative=float(values["collaborative"]),
        content=float(values["content"]),
        popularity=float(values["popularity"]),
    )
