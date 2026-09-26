import json
from importlib import import_module
from pathlib import Path

import pytest
from app.main import app, settings
from app.services.recommendation_reports import (
    available_recommendation_scopes,
    load_recommendation_report,
)
from fastapi.testclient import TestClient


def _report(root: Path) -> None:
    artifact = root / "movielens-32m-test"
    (artifact / "recommendations" / "demo").mkdir(parents=True)
    (artifact / "manifest.json").write_text("{}", encoding="utf-8")
    report = {
        "generated_at": "2026-01-01T00:00:00Z",
        "ranking_metrics": {"coverage": {"recommendations_returned": 2}},
        "recommendations": [
            {"tmdb_id": 1, "title": "Old", "year": 1950, "genres": ["Drama"]},
            {"tmdb_id": -2, "title": "New", "year": 2025, "genres": ["Horror"]},
        ],
        "lowest_recommendations": [
            {"tmdb_id": 3, "title": "Low Drama", "year": 2005, "genres": ["Drama"]}
        ],
    }
    (artifact / "recommendations" / "demo" / "all.json").write_text(
        json.dumps(report), encoding="utf-8"
    )


def test_report_filter_and_scope_listing(tmp_path: Path) -> None:
    _report(tmp_path)

    report = load_recommendation_report(tmp_path, "demo", year_min=2000)
    scopes = available_recommendation_scopes(tmp_path, "demo")

    assert [item["title"] for item in report["recommendations"]] == ["New"]
    assert report["api_filter"]["returned"] == 1
    assert report["source_ranking_metrics"]["coverage"]["recommendations_returned"] == 2
    assert scopes["scopes"][0]["scope"] == "all"

    horror = load_recommendation_report(tmp_path, "demo", genre="Horror")
    assert [item["title"] for item in horror["recommendations"]] == ["New"]
    assert horror["lowest_recommendations"] == []

    television = load_recommendation_report(tmp_path, "demo", media_type="tv")
    assert [item["title"] for item in television["recommendations"]] == ["New"]
    assert television["api_filter"]["media_type"] == "tv"

    movies = load_recommendation_report(tmp_path, "demo", media_type="movie")
    assert [item["title"] for item in movies["recommendations"]] == ["Old"]
    assert [item["title"] for item in movies["lowest_recommendations"]] == ["Low Drama"]


def test_report_rejects_unsafe_user_slug(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid user slug"):
        load_recommendation_report(tmp_path, "../secret")


def test_recommendation_api_serves_filtered_report(tmp_path: Path) -> None:
    _report(tmp_path)
    original = settings.ml_artifacts_dir
    settings.ml_artifacts_dir = tmp_path
    try:
        client = TestClient(app)
        response = client.get("/recommendations/demo?year_min=2000&media_type=tv&limit=1")
        scopes = client.get("/recommendations/demo/scopes")
    finally:
        settings.ml_artifacts_dir = original

    assert response.status_code == 200
    assert response.json()["recommendations"][0]["title"] == "New"
    assert scopes.status_code == 200
    assert scopes.json()["scopes"][0]["scope"] == "all"


def test_ui_disables_cache_and_movie_search_returns_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(tmp_path)
    main_module = import_module("app.main")
    original = settings.ml_artifacts_dir
    settings.ml_artifacts_dir = tmp_path
    monkeypatch.setattr(
        main_module,
        "generate_recommendations",
        lambda *args, **kwargs: {
            "candidates_considered": 1,
                "recommendations": [
                    {"tmdb_id": 348, "title": "Alien", "expected_rating": 4.2}
                ],
        },
    )
    monkeypatch.setattr(main_module, "_tmdb_search_ids", lambda *_args: [348])
    try:
        client = TestClient(app)
        page = client.get("/")
        search = client.get("/movies/search/demo?q=Alien")
    finally:
        settings.ml_artifacts_dir = original

    assert page.headers["cache-control"] == "no-store, max-age=0"
    assert "app.js?v=" in page.text
    assert search.status_code == 200
    assert search.json()["results"][0]["expected_rating"] == 4.2


def test_refresh_persists_profile_ranking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _report(tmp_path)
    main_module = import_module("app.main")
    original = settings.ml_artifacts_dir
    settings.ml_artifacts_dir = tmp_path
    captured: dict = {}

    def fake_generate(*_args, **kwargs):
        captured.update(kwargs)
        return {"recommendations": [], "lowest_recommendations": []}

    monkeypatch.setattr(main_module, "generate_recommendations", fake_generate)
    monkeypatch.setattr(main_module, "refresh_review_policy", lambda *_args, **_kwargs: {})
    try:
        response = TestClient(app).post("/recommendations/new-profile/refresh?limit=5")
    finally:
        settings.ml_artifacts_dir = original

    assert response.status_code == 200
    assert captured["persist"] is True
