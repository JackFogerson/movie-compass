from pathlib import Path

from app.services import group_recommendations as service


def _movie(tmdb_id: int, score: float, user: str) -> dict:
    return {
        "tmdb_id": tmdb_id,
        "title": f"Shared Movie {tmdb_id}",
        "year": 2000,
        "genres": ["Drama"],
        "expected_rating": score,
        "rating_uncertainty": {
            "plausible_minimum": score - 0.5,
            "plausible_maximum": score + 0.5,
        },
        "ranking_expectation": {
            "reason": f"Readable reason for {user}.",
            "evidence_level": "collaborative_supported",
        },
    }


def test_group_ranking_shows_every_person_and_protects_low_score(
    monkeypatch,
) -> None:
    def fake_generate(_artifact, *, user, candidate_tmdb_ids=None, **_kwargs):
        if candidate_tmdb_ids is None:
            return {"recommendations": [_movie(10, 4.5, user), _movie(20, 4.0, user)]}
        scores = {"alice": {10: 4.5, 20: 4.0}, "bob": {10: 3.5, 20: 4.2}}
        return {
            "recommendations": [
                _movie(tmdb_id, score, user) for tmdb_id, score in scores[user].items()
            ]
        }

    monkeypatch.setattr(service, "generate_recommendations", fake_generate)

    report = service.generate_group_recommendations(Path("artifact"), ["alice", "bob"], limit=2)

    assert report["users"] == ["alice", "bob"]
    assert report["recommendations"][0]["tmdb_id"] == 20
    assert len(report["recommendations"][0]["individual_scores"]) == 2
    assert "Scores run from" in report["recommendations"][0]["group_reason"]
    assert report["most_divisive"][0]["tmdb_id"] == 10
    assert "taste-split" in report["most_divisive"][0]["group_reason"]
    assert "bob is predicted at 4.20" in report["most_divisive"][1]["group_reason"]


def test_group_title_search_scores_each_profile_once(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_generate(_artifact, *, user, title_query=None, **_kwargs):
        calls.append((user, title_query))
        return {"recommendations": [_movie(10, 4.0 if user == "alice" else 3.5, user)]}

    monkeypatch.setattr(service, "generate_recommendations", fake_generate)
    report = service.generate_group_recommendations(
        Path("artifact"), ["alice", "bob"], title_query="Alien", bottom_limit=0
    )

    assert sorted(calls) == [("alice", "Alien"), ("bob", "Alien")]
    assert report["recommendations"][0]["tmdb_id"] == 10
    assert report["lowest_recommendations"] == []


def test_group_exact_tmdb_search_scores_the_requested_ids(monkeypatch) -> None:
    calls = []

    def fake_generate(_artifact, *, user, candidate_tmdb_ids=None, **_kwargs):
        calls.append((user, candidate_tmdb_ids))
        return {"recommendations": [_movie(348, 4.0, user)]}

    monkeypatch.setattr(service, "generate_recommendations", fake_generate)
    report = service.generate_group_recommendations(
        Path("exact-artifact"),
        ["alice", "bob"],
        candidate_tmdb_ids="348",
        bottom_limit=0,
    )

    assert sorted(calls) == [("alice", "348"), ("bob", "348")]
    assert report["recommendations"][0]["tmdb_id"] == 348


def test_divisive_list_scores_person_specific_candidate_union(monkeypatch) -> None:
    def fake_generate(_artifact, *, user, candidate_tmdb_ids=None, **_kwargs):
        if candidate_tmdb_ids is None:
            tmdb_id = 10 if user == "alice" else 20
            return {"recommendations": [_movie(tmdb_id, 4.5, user)]}
        scores = {"alice": {10: 4.5, 20: 3.5}, "bob": {10: 3.4, 20: 4.4}}
        return {
            "recommendations": [
                _movie(tmdb_id, score, user) for tmdb_id, score in scores[user].items()
            ]
        }

    service.clear_group_recommendation_cache()
    monkeypatch.setattr(service, "generate_recommendations", fake_generate)
    report = service.generate_group_recommendations(
        Path("union-artifact"), ["alice", "bob"], limit=2, divisive_limit=2
    )

    enthusiasts = [
        max(movie["individual_scores"], key=lambda item: item["expected_rating"])["user"]
        for movie in report["most_divisive"]
    ]
    assert enthusiasts == ["alice", "bob"]
    assert report["eligible_for_everyone"] == 2


def test_group_rewatch_penalty_scales_with_watched_fraction(monkeypatch) -> None:
    def fake_generate(_artifact, *, user, **_kwargs):
        return {"recommendations": [_movie(10, 4.0, user)]}

    monkeypatch.setattr(service, "generate_recommendations", fake_generate)
    monkeypatch.setattr(
        service,
        "_watched_by_user",
        lambda _users: {"alice": {10}, "bob": set()},
    )
    report = service.generate_group_recommendations(
        Path("artifact"),
        ["alice", "bob"],
        title_query="Shared",
        include_watched=True,
        bottom_limit=0,
    )

    movie = report["recommendations"][0]
    assert movie["unpenalized_group_score"] == 4.0
    assert movie["watched_fraction"] == 0.5
    assert movie["rewatch_penalty"] == 0.1
    assert movie["group_score"] == 3.9
