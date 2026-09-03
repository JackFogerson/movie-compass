from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

SUPPORTED_FILES = {
    "ratings.csv",
    "watched.csv",
    "diary.csv",
    "reviews.csv",
    "watchlist.csv",
    "likes/films.csv",
}


def _normalized_member(name: str) -> str:
    parts = Path(name.replace("\\", "/")).parts
    lowered = tuple(part.lower() for part in parts)
    if len(lowered) >= 2 and lowered[-2:] == ("likes", "films.csv"):
        return "likes/films.csv"
    excluded_sections = {"deleted", "orphaned", "likes"}
    if any(part in excluded_sections for part in lowered[:-1]):
        return "/".join(lowered)
    return lowered[-1]


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_year(value: str | None) -> int | None:
    try:
        year = int(value or "")
        return year if 1870 <= year <= 2200 else None
    except ValueError:
        return None


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


@dataclass
class LetterboxdMovie:
    name: str
    year: int | None
    letterboxd_uri: str | None = None
    rating: float | None = None
    watched: bool = False
    watched_dates: set[date] = field(default_factory=set)
    review_text: str | None = None
    review_date: date | None = None
    diary_entries: int = 0
    rewatch_count: int = 0
    liked: bool | None = None
    watchlisted: bool = False

    @property
    def source_key(self) -> str:
        return self.letterboxd_uri or f"{normalize_title(self.name)}:{self.year or ''}"

    def to_dict(self) -> dict:
        result = asdict(self)
        result["watched_dates"] = sorted(value.isoformat() for value in self.watched_dates)
        result["source_key"] = self.source_key
        return result


@dataclass(frozen=True)
class ImportReport:
    archive_files: tuple[str, ...]
    unsupported_files: tuple[str, ...]
    total_movies: int
    ratings: int
    watched: int
    diary_entries: int
    reviews: int
    watchlist_entries: int
    likes: int


def _rows(bundle: zipfile.ZipFile, member: str) -> list[dict[str, str]]:
    with bundle.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(text))


def parse_export(archive_path: Path) -> tuple[list[LetterboxdMovie], ImportReport]:
    if not zipfile.is_zipfile(archive_path):
        raise ValueError(f"Not a valid Letterboxd export ZIP: {archive_path}")
    movies: dict[str, LetterboxdMovie] = {}
    counts = {"ratings": 0, "watched": 0, "diary": 0, "reviews": 0, "watchlist": 0, "likes": 0}
    with zipfile.ZipFile(archive_path) as bundle:
        member_map = {
            _normalized_member(name): name for name in bundle.namelist() if not name.endswith("/")
        }

        def consume(logical: str, kind: str) -> None:
            member = member_map.get(logical)
            if not member:
                return
            for row in _rows(bundle, member):
                name = (row.get("Name") or row.get("Title") or "").strip()
                if not name:
                    continue
                year = _parse_year(row.get("Year"))
                uri = (row.get("Letterboxd URI") or "").strip() or None
                key = f"{normalize_title(name)}:{year or ''}"
                movie = movies.setdefault(
                    key, LetterboxdMovie(name=name, year=year, letterboxd_uri=uri)
                )
                if kind in {"ratings", "watched", "watchlist", "likes"} and uri:
                    movie.letterboxd_uri = uri
                if kind == "ratings":
                    try:
                        movie.rating = float(row.get("Rating") or "")
                    except ValueError:
                        pass
                elif kind in {"watched", "diary", "reviews"}:
                    movie.watched = True
                    watched_date = _parse_date(row.get("Watched Date") or row.get("Date"))
                    if watched_date:
                        movie.watched_dates.add(watched_date)
                    if kind == "diary":
                        movie.diary_entries += 1
                        if (row.get("Rewatch") or "").strip().casefold() in {
                            "yes",
                            "true",
                            "1",
                        }:
                            movie.rewatch_count += 1
                    if kind == "reviews":
                        review_text = (
                            row.get("Review") or row.get("Review Text") or ""
                        ).strip() or None
                        review_date = _parse_date(row.get("Watched Date") or row.get("Date"))
                        if review_text and (
                            movie.review_text is None
                            or (
                                review_date is not None
                                and (movie.review_date is None or review_date >= movie.review_date)
                            )
                        ):
                            movie.review_text = review_text
                            movie.review_date = review_date
                elif kind == "watchlist":
                    movie.watchlisted = True
                elif kind == "likes":
                    movie.liked = True
                counts[kind] += 1

        for logical, kind in (
            ("ratings.csv", "ratings"),
            ("watched.csv", "watched"),
            ("diary.csv", "diary"),
            ("reviews.csv", "reviews"),
            ("watchlist.csv", "watchlist"),
            ("likes/films.csv", "likes"),
        ):
            consume(logical, kind)
        present = tuple(sorted(member_map))
        unsupported = tuple(sorted(name for name in present if name not in SUPPORTED_FILES))
    report = ImportReport(
        present,
        unsupported,
        len(movies),
        counts["ratings"],
        counts["watched"],
        counts["diary"],
        counts["reviews"],
        counts["watchlist"],
        counts["likes"],
    )
    return list(movies.values()), report
