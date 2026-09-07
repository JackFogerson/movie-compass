from pathlib import Path

from app.services import review_policy as service


def test_review_policy_handles_missing_cache_on_fresh_install(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(service, "personal_tmdb_ratings", lambda *_args: {})
    monkeypatch.setattr(service, "personal_tmdb_reviews", lambda *_args: {})
    output = tmp_path / "processed" / "review-policies" / "new-user.json"

    policy = service.refresh_review_policy(
        "new-user",
        tmp_path / "processed" / "tmdb-rich-details.json",
        output,
    )

    assert policy["enabled"] is False
    assert output.is_file()
