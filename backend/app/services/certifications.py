from __future__ import annotations

UNKNOWN_CERTIFICATION = "Unknown / not rated"


def us_certification(details: dict) -> str | None:
    """Return the most useful US movie or TV certification in a TMDB detail record."""
    direct = str(details.get("certification") or "").strip()
    if direct and direct != UNKNOWN_CERTIFICATION:
        return direct

    release_results = (details.get("release_dates") or {}).get("results", [])
    us_release = next(
        (
            item
            for item in release_results
            if isinstance(item, dict) and item.get("iso_3166_1") == "US"
        ),
        None,
    )
    if us_release:
        release_priority = {3: 0, 2: 1, 4: 2, 5: 3, 6: 4, 1: 5}
        candidates = [
            item
            for item in us_release.get("release_dates", [])
            if isinstance(item, dict) and str(item.get("certification") or "").strip()
        ]
        if candidates:
            candidates.sort(key=lambda item: release_priority.get(int(item.get("type") or 0), 9))
            return str(candidates[0]["certification"]).strip()

    rating_results = (details.get("content_ratings") or {}).get("results", [])
    us_rating = next(
        (
            str(item.get("rating") or "").strip()
            for item in rating_results
            if isinstance(item, dict) and item.get("iso_3166_1") == "US"
        ),
        "",
    )
    return us_rating or None


def certification_bucket(certification: str | None) -> str:
    """Map TMDB's historical and current US labels into stable filter groups."""
    normalized = str(certification or "").strip().upper()
    if normalized in {"G", "PG", "PG-13", "R", "NC-17"}:
        return normalized.lower()
    if normalized in {"NR", "UNRATED", "NOT RATED"}:
        return "unrated"
    if not normalized or normalized == UNKNOWN_CERTIFICATION.upper():
        return "unknown"
    return "other"
