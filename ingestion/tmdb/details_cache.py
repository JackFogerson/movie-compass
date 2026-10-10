from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Protocol

from ingestion.tmdb.client import (
    TmdbNotFound,
    is_tv_catalog_id,
    normalize_tv_details,
)


class DetailsClient(Protocol):
    def movie_details(self, tmdb_id: int, append_to_response: str | None = None) -> dict: ...

    def tv_details(self, tmdb_id: int, append_to_response: str | None = None) -> dict: ...


_CACHE_LOCK = RLock()


def _write_cache(path: Path, values: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.part")
    temporary.write_text(json.dumps(values), encoding="utf-8")
    temporary.replace(path)


def merge_discovery_results(cache_path: Path, rows: list[dict]) -> None:
    """Persist lightweight discover rows without replacing richer cached details."""
    if not rows:
        return
    with _CACHE_LOCK:
        cached: dict[str, dict] = {}
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        changed = False
        for row in rows:
            if row.get("id") is None:
                continue
            key = str(int(row["id"]))
            existing = cached.get(key)
            if existing and existing.get("missing") is not True:
                # Existing rich fields win. Discovery fills only absent fields.
                merged = dict(row)
                merged.update(existing)
                if merged != existing:
                    cached[key] = merged
                    changed = True
            else:
                cached[key] = row
                changed = True
        if changed:
            _write_cache(cache_path, cached)


def load_or_fetch_details(
    client: DetailsClient,
    tmdb_ids: set[int],
    cache_path: Path,
    *,
    save_every: int = 20,
) -> tuple[dict[int, dict], int]:
    with _CACHE_LOCK:
        return _load_or_fetch_details_locked(
            client,
            tmdb_ids,
            cache_path,
            save_every=save_every,
        )


def _load_or_fetch_details_locked(
    client: DetailsClient,
    tmdb_ids: set[int],
    cache_path: Path,
    *,
    save_every: int,
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
                and existing.get("release_dates") is not None
            ):
                continue
            fetched += 1
            try:
                if is_tv_catalog_id(tmdb_id):
                    cached[key] = normalize_tv_details(
                        client.tv_details(
                            abs(tmdb_id),
                            "credits,keywords,content_ratings",
                        )
                    )
                else:
                    cached[key] = client.movie_details(
                        tmdb_id,
                        "credits,keywords,release_dates",
                    )
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
