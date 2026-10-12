import json
import zipfile
from pathlib import Path

from app.services.profile_source import (
    incoming_letterboxd_profile,
    letterboxd_profile_from_filename,
    profile_source_mismatch,
)


def test_standard_letterboxd_export_filename_retains_profile() -> None:
    assert (
        letterboxd_profile_from_filename("letterboxd-jackalthegreat-2026-10-12-00-15-utc.zip")
        == "jackalthegreat"
    )
    assert letterboxd_profile_from_filename("movie-compass-jack.zip") is None
    assert letterboxd_profile_from_filename("letterboxd.zip") is None


def test_movie_compass_backup_carries_letterboxd_profile(tmp_path: Path) -> None:
    archive = tmp_path / "movie-compass-viewer.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "movie-compass-profile.json",
            json.dumps(
                {
                    "format": "movie-compass-profile",
                    "version": 2,
                    "letterboxd_profile": "FrostyFog",
                }
            ),
        )
    assert incoming_letterboxd_profile(archive.name, archive) == "frostyfog"


def test_mismatch_requires_two_known_different_profiles() -> None:
    assert profile_source_mismatch("jackalthegreat", "frostyfog") is True
    assert profile_source_mismatch("JackalTheGreat", "jackalthegreat") is False
    assert profile_source_mismatch("jackalthegreat", None) is False
