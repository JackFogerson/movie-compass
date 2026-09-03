from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import httpx


@dataclass(frozen=True)
class DailyExportSummary:
    export_date: str
    source_url: str
    source_sha256: str
    records: int
    eligible_movies: int
    adult_movies_excluded: int
    video_records_excluded: int
    popularity_positive: int
    maximum_tmdb_id: int
    generated_at: str


def export_url(export_date: date) -> str:
    filename = f"movie_ids_{export_date:%m_%d_%Y}.json.gz"
    return f"https://files.tmdb.org/p/exports/{filename}"


def download_daily_export(
    export_date: date,
    target: Path,
    *,
    transport: httpx.BaseTransport | None = None,
) -> tuple[str, str]:
    """Download one official TMDB daily ID export atomically."""
    url = export_url(export_date)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.part")
    digest = hashlib.sha256()
    try:
        with httpx.Client(timeout=60, transport=transport, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        digest.update(chunk)
                        handle.write(chunk)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return url, digest.hexdigest()


def build_catalog_index(
    archive: Path,
    database: Path,
    *,
    export_date: date,
    source_url: str,
    source_sha256: str,
    manifest_path: Path,
) -> DailyExportSummary:
    """Stream the line-delimited gzip export into a compact searchable SQLite index."""
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_suffix(f"{database.suffix}.part")
    if temporary.exists():
        temporary.unlink()
    connection = sqlite3.connect(temporary)
    records = eligible = adult = videos = popularity_positive = maximum_id = 0
    batch: list[tuple[int, float, int, int]] = []
    try:
        connection.execute(
            "CREATE TABLE movies (tmdb_id INTEGER PRIMARY KEY, popularity REAL NOT NULL, "
            "adult INTEGER NOT NULL, video INTEGER NOT NULL)"
        )
        with gzip.open(archive, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                tmdb_id = int(row["id"])
                popularity = float(row.get("popularity") or 0.0)
                is_adult = int(bool(row.get("adult")))
                is_video = int(bool(row.get("video")))
                batch.append((tmdb_id, popularity, is_adult, is_video))
                records += 1
                adult += is_adult
                videos += is_video
                popularity_positive += int(popularity > 0)
                eligible += int(not is_adult and not is_video)
                maximum_id = max(maximum_id, tmdb_id)
                if len(batch) >= 10_000:
                    connection.executemany("INSERT INTO movies VALUES (?, ?, ?, ?)", batch)
                    batch.clear()
        if batch:
            connection.executemany("INSERT INTO movies VALUES (?, ?, ?, ?)", batch)
        connection.execute("CREATE INDEX movies_popularity ON movies(popularity DESC)")
        connection.commit()
    except Exception:
        connection.close()
        if temporary.exists():
            temporary.unlink()
        raise
    connection.close()
    temporary.replace(database)
    summary = DailyExportSummary(
        export_date=export_date.isoformat(),
        source_url=source_url,
        source_sha256=source_sha256,
        records=records,
        eligible_movies=eligible,
        adult_movies_excluded=adult,
        video_records_excluded=videos,
        popularity_positive=popularity_positive,
        maximum_tmdb_id=maximum_id,
        generated_at=datetime.now(UTC).isoformat(),
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(asdict(summary), indent=2), encoding="utf-8")
    return summary


def load_catalog_summary(manifest_path: Path) -> dict | None:
    if not manifest_path.is_file():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))
