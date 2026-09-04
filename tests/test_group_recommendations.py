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
        "metadata_matches": ["genre: drama", "story/theme: friendship"],
        "caution_matches": ["story/theme: bleak ending"],
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
    assert "worked well for every profile" in report["recommendations"][0]["group_reason"]
    assert "story/theme:" not in report["recommendations"][0]["group_reason"]
    assert report["most_divisive"][0]["tmdb_id"] == 10
    assert report["most_divisive"][0]["featured_enthusiast"] == "alice"
    assert report["most_divisive"][0]["featured_enthusiasm_rank"] == 1
    assert "biggest enthusiast split" in report["most_divisive"][0]["group_reason"]
    assert report["most_divisive"][1]["featured_enthusiast"] == "bob"
    assert "bob's biggest enthusiast split" in report["most_divisive"][1]["group_reason"]


def test_group_bottom_five_uses_cautious_explanation(monkeypatch) -> None:
    def fake_generate(_artifact, *, user, candidate_tmdb_ids=None, **_kwargs):
        movies = [
            _movie(10, 4.2 if user == "alice" else 4.0, user),
            _movie(20, 2.0 if user == "alice" else 2.2, user),
        ]
        for movie in movies:
            movie["why_you_may_not_like_it"] = ["Its strongest traits match lower ratings."]
        return {"recommendations": movies, "lowest_recommendations": movies}

    monkeypatch.setattr(service, "generate_recommendations", fake_generate)
    report = service.generate_group_recommendations(
        Path("bottom-artifact"), ["alice", "bob"], limit=1, bottom_limit=1
    )

    lowest = report["lowest_recommendations"][0]
    assert "falls near the bottom" in lowest["group_reason"]
    assert len(lowest["why_you_may_not_like_it"]) >= 2


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


def test_split_section_returns_one_enthusiast_movie_per_person(monkeypatch) -> None:
    users = ["alice", "bob", "carol"]
    scores = {
        "alice": {10: 4.8, 20: 2.8, 30: 3.0},
        "bob": {10: 2.9, 20: 4.7, 30: 2.7},
        "carol": {10: 2.6, 20: 2.5, 30: 4.6},
    }

    def fake_generate(_artifact, *, user, candidate_tmdb_ids=None, **_kwargs):
        if candidate_tmdb_ids is None:
            return {
                "recommendations": [
                    _movie(tmdb_id, scores[user][tmdb_id], user)
                    for tmdb_id in (10, 20, 30)
                ]
            }
        return {
            "recommendations": [
                _movie(tmdb_id, scores[user][tmdb_id], user) for tmdb_id in (10, 20, 30)
            ]
        }

    monkeypatch.setattr(service, "generate_recommendations", fake_generate)
    report = service.generate_group_recommendations(
        Path("three-person-artifact"), users, limit=3
    )

    assert [movie["featured_enthusiast"] for movie in report["most_divisive"]] == users
    assert [movie["tmdb_id"] for movie in report["most_divisive"]] == [10, 20, 30]


def test_split_section_falls_back_to_second_place_instead_of_dropping_person(
    monkeypatch,
) -> None:
    users = ["alice", "bob", "carol"]
    scores = {
        "alice": {10: 4.8, 20: 4.6, 30: 4.2},
        "bob": {10: 4.0, 20: 3.0, 30: 3.8},
        "carol": {10: 3.5, 20: 3.9, 30: 3.2},
    }

    def fake_generate(_artifact, *, user, **_kwargs):
        return {
            "recommendations": [
                _movie(tmdb_id, scores[user][tmdb_id], user) for tmdb_id in (10, 20, 30)
            ]
        }

    monkeypatch.setattr(service, "generate_recommendations", fake_generate)
    report = service.generate_group_recommendations(
        Path("fallback-artifact"), users, limit=3
    )
    by_user = {movie["featured_enthusiast"]: movie for movie in report["most_divisive"]}

    assert set(by_user) == set(users)
    assert by_user["bob"]["featured_enthusiasm_rank"] == 2
    assert by_user["bob"]["tmdb_id"] == 30
    assert "best 2nd-most-enthusiastic split" in by_user["bob"]["group_reason"]


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
