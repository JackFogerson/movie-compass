from pathlib import Path

from scripts.desktop_launcher import bundled_tmdb_key, load_tmdb_key


def test_desktop_uses_build_injected_tmdb_key_without_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    resources = tmp_path / "resources"
    local_root = tmp_path / "local"
    key_path = resources / "data" / "bootstrap" / "tmdb-access.key"
    key_path.parent.mkdir(parents=True)
    key_path.write_text("shared-test-key", encoding="utf-8")
    monkeypatch.delenv("TMDB_API_KEY", raising=False)

    assert bundled_tmdb_key(resources) == "shared-test-key"
    assert load_tmdb_key(resources, local_root) == "shared-test-key"


def test_desktop_environment_key_overrides_build_injected_key(
    tmp_path: Path, monkeypatch
) -> None:
    resources = tmp_path / "resources"
    key_path = resources / "data" / "bootstrap" / "tmdb-access.key"
    key_path.parent.mkdir(parents=True)
    key_path.write_text("shared-test-key", encoding="utf-8")
    monkeypatch.setenv("TMDB_API_KEY", "environment-test-key")

    assert load_tmdb_key(resources, tmp_path / "local") == "environment-test-key"
