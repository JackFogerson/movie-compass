from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.core.config import get_settings
from app.services.certifications import us_certification
from ingestion.tmdb.client import TmdbClient, TmdbNotFound


def _load(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, values: dict[str, dict]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.part")
    temporary.write_text(json.dumps(values), encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    """Backfill regional US certifications into portable and working TMDB caches."""
    settings = get_settings()
    paths = [
        settings.data_dir / "bootstrap" / "tmdb-rich-details.json",
        settings.processed_data_dir / "tmdb-rich-details.json",
    ]
    caches = {path: _load(path) for path in paths if path.is_file()}
    movie_ids = {
        int(raw_id)
        for cache in caches.values()
        for raw_id, details in cache.items()
        if str(raw_id).isdigit()
        and isinstance(details, dict)
        and details.get("missing") is not True
    }
    already_known = {
        movie_id
        for movie_id in movie_ids
        if any(
            str(movie_id) in cache and cache[str(movie_id)].get("release_dates") is not None
            for cache in caches.values()
        )
    }
    pending = sorted(movie_ids - already_known)
    client = TmdbClient(settings.tmdb_api_key)
    fetched: dict[int, dict] = {}
    failures = 0

    def fetch(movie_id: int) -> tuple[int, dict | None]:
        try:
            details = client.movie_details(movie_id, "release_dates")
            return movie_id, details.get("release_dates") or {"results": []}
        except TmdbNotFound:
            return movie_id, {"results": []}
        except Exception:
            return movie_id, None

    try:
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(fetch, movie_id): movie_id for movie_id in pending}
            for index, future in enumerate(as_completed(futures), start=1):
                movie_id, release_dates = future.result()
                if release_dates is None:
                    failures += 1
                else:
                    fetched[movie_id] = release_dates
                if index % 100 == 0:
                    print(f"Fetched certifications for {index}/{len(pending)} movies")
    finally:
        client.close()

    for path, cache in caches.items():
        for raw_id, details in cache.items():
            if not str(raw_id).isdigit() or not isinstance(details, dict):
                continue
            movie_id = int(raw_id)
            if movie_id in fetched:
                details["release_dates"] = fetched[movie_id]
            elif movie_id in already_known:
                for source in caches.values():
                    source_details = source.get(str(movie_id), {})
                    if source_details.get("release_dates") is not None:
                        details["release_dates"] = source_details["release_dates"]
                        break
        _write(path, cache)

    known = sum(
        us_certification(details) is not None
        for details in caches[paths[0]].values()
        if isinstance(details, dict) and details.get("missing") is not True
    )
    total = sum(
        isinstance(details, dict) and details.get("missing") is not True
        for details in caches[paths[0]].values()
    )
    print(
        f"Portable catalog certification coverage: {known}/{total} "
        f"({known / total:.1%}); unknown/not rated: {total - known}/{total} "
        f"({(total - known) / total:.1%})"
    )
    if failures:
        print(f"Temporary TMDB failures left for a later retry: {failures}")


if __name__ == "__main__":
    main()
