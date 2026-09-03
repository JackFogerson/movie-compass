from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from ingestion.tmdb.client import TmdbNotFound


class DetailsClient(Protocol):
    def movie_details(self, tmdb_id: int, append_to_response: str | None = None) -> dict: ...


def _write_cache(path: Path, values: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.part")
    temporary.write_text(json.dumps(values), encoding="utf-8")
    temporary.replace(path)


def load_or_fetch_details(
    client: DetailsClient,
    tmdb_ids: set[int],
    cache_path: Path,
    *,
    save_every: int = 20,
) -> tuple[dict[int, dict], int]:
    cached: dict[str, dict] = {}
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    fetched = 0
    try:
        for tmdb_id in sorted(tmdb_ids):
            key = str(tmdb_id)
            existing = cached.get(key)
            if existing and existing.get("missing") is True:
                continue
            if (
                existing
                and existing.get("credits") is not None
                and existing.get("keywords") is not None
            ):
                continue
            fetched += 1
            try:
                cached[key] = client.movie_details(tmdb_id, "credits,keywords")
            except TmdbNotFound:
                cached[key] = {"id": tmdb_id, "missing": True}
            if fetched % save_every == 0:
                _write_cache(cache_path, cached)
    finally:
        if fetched:
            _write_cache(cache_path, cached)
    available = {
        tmdb_id: cached[str(tmdb_id)]
        for tmdb_id in tmdb_ids
        if str(tmdb_id) in cached and cached[str(tmdb_id)].get("missing") is not True
    }
    return available, fetched
