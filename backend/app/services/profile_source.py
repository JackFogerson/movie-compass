from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ImportRun

LETTERBOXD_EXPORT = re.compile(
    r"^letterboxd-(?P<profile>.+)-\d{4}-\d{2}-\d{2}(?:[-_].*)?\.zip$",
    re.IGNORECASE,
)


def normalize_letterboxd_profile(value: object) -> str | None:
    profile = str(value or "").strip().lstrip("@").strip()
    if not profile or len(profile) > 100:
        return None
    return profile.casefold()


def letterboxd_profile_from_filename(filename: str | None) -> str | None:
    """Read the account portion of Letterboxd's standard export filename."""
    basename = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    match = LETTERBOXD_EXPORT.fullmatch(basename)
    return normalize_letterboxd_profile(match.group("profile")) if match else None


def letterboxd_profile_from_archive(path: Path) -> str | None:
    """Recover the source account carried by a Movie Compass profile backup."""
    try:
        with zipfile.ZipFile(path) as bundle:
            if "movie-compass-profile.json" not in bundle.namelist():
                return None
            manifest = json.loads(bundle.read("movie-compass-profile.json"))
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError):
        return None
    return normalize_letterboxd_profile(manifest.get("letterboxd_profile"))


def incoming_letterboxd_profile(filename: str | None, path: Path) -> str | None:
    return letterboxd_profile_from_archive(path) or letterboxd_profile_from_filename(filename)


def stored_letterboxd_profile(session: Session, user_id: int) -> str | None:
    """Return the first trustworthy Letterboxd account recorded for a profile."""
    runs = session.scalars(
        select(ImportRun)
        .where(ImportRun.user_id == user_id, ImportRun.source == "letterboxd")
        .order_by(ImportRun.started_at, ImportRun.id)
    ).all()
    for run in runs:
        try:
            report = json.loads(run.report_json or "{}")
        except json.JSONDecodeError:
            report = {}
        identity = normalize_letterboxd_profile(report.get("letterboxd_profile"))
        if identity:
            return identity
        identity = letterboxd_profile_from_filename(run.archive_name)
        if identity:
            return identity
    return None


def profile_source_mismatch(expected: str | None, incoming: str | None) -> bool:
    return bool(expected and incoming and expected.casefold() != incoming.casefold())
