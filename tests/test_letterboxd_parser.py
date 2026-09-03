import csv
import io
import zipfile
from pathlib import Path

from ingestion.letterboxd.parser import normalize_title, parse_export


def _csv(rows: list[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def test_parse_export_merges_interactions_and_handles_missing_files(tmp_path: Path) -> None:
    archive = tmp_path / "letterboxd.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "ratings.csv",
            _csv(
                [
                    {
                        "Date": "2024-01-01",
                        "Name": "Arrival",
                        "Year": "2016",
                        "Letterboxd URI": "https://boxd.it/ed3g",
                        "Rating": "4.5",
                    }
                ]
            ),
        )
        bundle.writestr(
            "diary.csv",
            _csv(
                [
                    {
                        "Date": "2024-02-03",
                        "Name": "Arrival",
                        "Year": "2016",
                        "Letterboxd URI": "https://boxd.it/ed3g",
                        "Rewatch": "No",
                    }
                ]
            ),
        )
        bundle.writestr(
            "watchlist.csv",
            _csv(
                [
                    {
                        "Date": "2024-03-01",
                        "Name": "Solaris",
                        "Year": "1972",
                        "Letterboxd URI": "https://boxd.it/2a2Y",
                    }
                ]
            ),
        )
    movies, report = parse_export(archive)
    assert report.total_movies == 2
    assert report.ratings == 1
    assert report.diary_entries == 1
    assert report.watchlist_entries == 1
    arrival = next(movie for movie in movies if movie.name == "Arrival")
    assert arrival.rating == 4.5
    assert arrival.watched is True
    assert {value.isoformat() for value in arrival.watched_dates} == {"2024-02-03"}


def test_normalize_title_is_stable() -> None:
    assert normalize_title("Amélie: The Movie!") == "am lie the movie"


def test_deleted_and_liked_review_files_do_not_override_root_reviews(tmp_path: Path) -> None:
    archive = tmp_path / "letterboxd.zip"
    root_review = {
        "Date": "2024-01-01",
        "Name": "Arrival",
        "Year": "2016",
        "Letterboxd URI": "https://boxd.it/ed3g",
        "Review": "The real review",
    }
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("reviews.csv", _csv([root_review]))
        bundle.writestr("deleted/reviews.csv", _csv([{**root_review, "Review": "Deleted"}]))
        bundle.writestr("likes/reviews.csv", _csv([{**root_review, "Review": "Liked"}]))
    movies, report = parse_export(archive)
    assert report.reviews == 1
    assert movies[0].review_text == "The real review"


def test_entry_specific_review_uri_merges_with_film_uri(tmp_path: Path) -> None:
    archive = tmp_path / "letterboxd.zip"
    rating = {
        "Date": "2024-01-01",
        "Name": "Arrival",
        "Year": "2016",
        "Letterboxd URI": "https://boxd.it/ed3g",
        "Rating": "4.5",
    }
    review = {
        **rating,
        "Letterboxd URI": "https://boxd.it/activity-review-id",
        "Review": "Thoughtful science fiction",
    }
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("ratings.csv", _csv([rating]))
        bundle.writestr("reviews.csv", _csv([review]))
    movies, _ = parse_export(archive)
    assert len(movies) == 1
    assert movies[0].letterboxd_uri == "https://boxd.it/ed3g"
    assert movies[0].review_text == "Thoughtful science fiction"


def test_latest_review_wins_and_explicit_rewatch_is_counted(tmp_path: Path) -> None:
    archive = tmp_path / "letterboxd.zip"
    base = {
        "Name": "Arrival",
        "Year": "2016",
        "Letterboxd URI": "https://boxd.it/review-entry",
        "Rating": "4.5",
        "Rewatch": "No",
    }
    reviews = [
        {**base, "Date": "2026-08-31", "Watched Date": "2026-08-30", "Review": "Latest"},
        {**base, "Date": "2026-01-01", "Watched Date": "2025-12-31", "Review": "Older"},
    ]
    diary = [
        {**base, "Date": "2026-08-31", "Watched Date": "2026-08-30", "Rewatch": "Yes"},
        {**base, "Date": "2026-01-01", "Watched Date": "2025-12-31", "Rewatch": "No"},
    ]
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("reviews.csv", _csv(reviews))
        bundle.writestr("diary.csv", _csv(diary))
    movies, _ = parse_export(archive)
    assert movies[0].review_text == "Latest"
    assert movies[0].review_date.isoformat() == "2026-08-30"
    assert movies[0].diary_entries == 2
    assert movies[0].rewatch_count == 1
