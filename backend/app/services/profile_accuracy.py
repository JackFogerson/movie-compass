from __future__ import annotations

import json
from datetime import UTC, datetime
from math import sqrt
from pathlib import Path
from random import Random
from statistics import mean
from threading import Lock

from app.cli.recommend import _load_shared_recommender_assets
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.model_weights import select_personalized_weights, weights_from_policy
from app.services.personal_ratings import linked_personal_ratings, personal_tmdb_ratings
from ml.evaluation.personal import evaluate_personal_ratings
from recommendation.baselines.tmdb_content import TmdbContentModel

_CACHE: dict[tuple[str, str, tuple[tuple[int, float], ...]], dict] = {}
_CACHE_LOCK = Lock()
_SEEDS = (1, 7, 21, 42, 84)


def _calibration_band(prediction: float) -> str:
    if prediction < 2.5:
        return "Below 2.5"
    if prediction < 3.5:
        return "2.5–3.4"
    if prediction < 4.2:
        return "3.5–4.1"
    return "4.2+"


def _tmdb_heldout_evaluations(
    ratings: dict[int, float], cold_start_weights: dict[str, float]
) -> tuple[list[dict], int]:
    settings = get_settings()
    cache_path = settings.processed_data_dir / "tmdb-rich-details.json"
    details = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    details_by_id = {int(key): value for key, value in details.items()}
    ids = sorted(set(ratings).intersection(details_by_id))
    if len(ids) < 10:
        raise ValueError("At least ten metadata-linked personal ratings are required")
    evaluations = []
    for seed in _SEEDS:
        shuffled = ids.copy()
        Random(seed).shuffle(shuffled)
        test_size = max(2, round(len(shuffled) * 0.2))
        test_ids = shuffled[:test_size]
        train_ids = shuffled[test_size:]
        train_ratings = {tmdb_id: ratings[tmdb_id] for tmdb_id in train_ids}
        model = TmdbContentModel.fit(details_by_id, train_ratings)
        content = model.predict({tmdb_id: details_by_id[tmdb_id] for tmdb_id in test_ids})
        rows = []
        for tmdb_id in test_ids:
            item = details_by_id[tmdb_id]
            reliability = float(item.get("vote_count") or 0)
            reliability /= reliability + 250.0
            public = float(item.get("vote_average") or model.user_mean * 2) / 2.0
            prior = reliability * public + (1.0 - reliability) * model.user_mean
            prediction = (
                float(cold_start_weights["metadata"]) * content[tmdb_id]
                + float(cold_start_weights["public_rating"]) * prior
            )
            rows.append(
                {
                    "actual": ratings[tmdb_id],
                    "metadata": content[tmdb_id],
                    "public_prior": prior,
                    "hybrid": prediction,
                }
            )
        evaluations.append({"errors": rows})
    return evaluations, len(ids)


def profile_accuracy(artifact_dir: Path, user: str) -> dict:
    """Evaluate a profile on ratings hidden from its personal fit layer."""
    artifact_key = str(artifact_dir.resolve())
    catalog, _movie_ids, _manifest, collaborative, popularity = (
        _load_shared_recommender_assets(artifact_key)
    )
    with SessionLocal() as session:
        personal = linked_personal_ratings(session, user, catalog)
        tmdb_personal = personal_tmdb_ratings(session, user)
    details_path = get_settings().processed_data_dir / "tmdb-rich-details.json"
    details_raw = (
        json.loads(details_path.read_text(encoding="utf-8")) if details_path.is_file() else {}
    )
    details_by_id = {int(key): value for key, value in details_raw.items()}
    personal_details = {
        tmdb_id: details_by_id[tmdb_id]
        for tmdb_id in set(tmdb_personal).intersection(details_by_id)
    }
    use_movielens = len(personal) >= 10
    fingerprint_source = personal if use_movielens else tmdb_personal
    fingerprint = tuple(sorted((key, round(value, 3)) for key, value in fingerprint_source.items()))
    cache_key = (artifact_key, user, fingerprint)
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached
    weight_policy = select_personalized_weights(
        get_settings().processed_data_dir / "model-weights" / f"{user}.json",
        catalog,
        personal,
        popularity,
        collaborative,
        tmdb_details=personal_details,
        tmdb_ratings=tmdb_personal,
    )

    if use_movielens:
        raw_evaluations = [
            evaluate_personal_ratings(
                catalog,
                personal,
                popularity,
                collaborative,
                seed=seed,
                hybrid_weights=weights_from_policy(weight_policy),
            )
            for seed in _SEEDS
        ]
        errors = [row for evaluation in raw_evaluations for row in evaluation.errors]
        model_order = ("hybrid", "collaborative", "content", "popularity")
        comparisons = [
            {
                "model": model,
                "mae": round(mean(item.metrics[model].mae for item in raw_evaluations), 3),
                "rmse": round(mean(item.metrics[model].rmse for item in raw_evaluations), 3),
            }
            for model in model_order
        ]
        linked_count = len(personal)
        method = "Five repeated 80/20 held-out tests of the full hybrid model"
    else:
        raw_evaluations, linked_count = _tmdb_heldout_evaluations(
            tmdb_personal, weight_policy["cold_start_weights"]
        )
        errors = [row for evaluation in raw_evaluations for row in evaluation["errors"]]
        comparisons = []
        for model in ("hybrid", "metadata", "public_prior"):
            model_errors = [float(row[model]) - float(row["actual"]) for row in errors]
            comparisons.append(
                {
                    "model": model,
                    "mae": round(mean(abs(value) for value in model_errors), 3),
                    "rmse": round(sqrt(mean(value**2 for value in model_errors)), 3),
                }
            )
        method = "Five repeated 80/20 held-out tests of the TMDB metadata model"
    signed_errors = [float(row["hybrid"]) - float(row["actual"]) for row in errors]
    bias = mean(signed_errors)
    bands: dict[str, list[tuple[float, float]]] = {}
    for row in errors:
        prediction = float(row["hybrid"])
        bands.setdefault(_calibration_band(prediction), []).append(
            (prediction, float(row["actual"]))
        )
    calibration = [
        {
            "band": label,
            "predicted_average": round(mean(value[0] for value in values), 2),
            "actual_average": round(mean(value[1] for value in values), 2),
            "samples": len(values),
        }
        for label in ("Below 2.5", "2.5–3.4", "3.5–4.1", "4.2+")
        if (values := bands.get(label))
    ]
    reliability = "strong" if linked_count >= 70 else "useful" if linked_count >= 30 else "early"
    result = {
        "user": user,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "method": method,
        "linked_ratings": linked_count,
        "test_predictions": len(errors),
        "reliability": reliability,
        "mae": comparisons[0]["mae"],
        "rmse": comparisons[0]["rmse"],
        "within_half_star": round(
            100 * sum(abs(value) <= 0.5 for value in signed_errors) / len(signed_errors), 1
        ),
        "bias": round(bias, 3),
        "bias_label": (
            "runs high" if bias > 0.1 else "runs low" if bias < -0.1 else "well centered"
        ),
        "models": comparisons,
        "calibration": calibration,
        "personalized_weights": weight_policy,
    }
    with _CACHE_LOCK:
        _CACHE[cache_key] = result
    return result
