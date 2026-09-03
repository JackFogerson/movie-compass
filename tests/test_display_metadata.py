from app.services import display_metadata
from app.services.display_metadata import mood_labels, streaming_options


def test_mood_labels_are_readable_and_limited() -> None:
    details = {
        "genres": [
            {"name": "Horror"},
            {"name": "Comedy"},
            {"name": "Adventure"},
        ]
    }
    assert mood_labels(details) == ["Scary", "Funny"]


def test_streaming_options_use_country_and_monetization_type() -> None:
    details = {
        "watch_providers": {
            "results": {
                "US": {
                    "link": "https://example.test/watch",
                    "flatrate": [{"provider_name": "Example+", "logo_path": "/x.png"}],
                    "rent": [{"provider_name": "Example Store", "logo_path": None}],
                }
            }
        }
    }
    options, link = streaming_options(details, "US")
    assert options == [
        {"service": "Example+", "type": "subscription", "logo_path": "/x.png"},
        {"service": "Example Store", "type": "rent", "logo_path": None},
    ]
    assert link == "https://example.test/watch"


def test_display_metadata_falls_back_to_tv_provider_data(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, _api_key: str):
            pass

        def movie_details(self, _tmdb_id: int, _append: str) -> dict:
            raise RuntimeError("not a movie record")

        def search_tv(self, title: str, year: int | None) -> list[dict]:
            assert (title, year) == ("Band of Brothers", 2001)
            return [{"id": 4613, "name": title, "first_air_date": "2001-09-09"}]

        def tv_details(self, tmdb_id: int, _append: str) -> dict:
            assert tmdb_id == 4613
            return {
                "id": tmdb_id,
                "name": "Band of Brothers",
                "first_air_date": "2001-09-09",
                "episode_run_time": [60],
                "genres": [{"name": "Drama"}],
                "watch/providers": {
                    "results": {
                        "US": {
                            "link": "https://example.test/tv/4613/watch",
                            "flatrate": [{"provider_name": "Max"}],
                        }
                    }
                },
            }

        def close(self) -> None:
            pass

    monkeypatch.setattr(display_metadata, "TmdbClient", FakeClient)
    _, details = display_metadata._fetch_display_details(
        "key", 331214, "Band of Brothers", 2001
    )

    assert details is not None
    assert details["id"] == 4613
    assert details["media_type"] == "tv"
    assert details["runtime"] == 60
    assert details["runtime_label"] == "60 min/episode"
    options, link = streaming_options(details, "US")
    assert options[0]["service"] == "Max"
    assert link == "https://example.test/tv/4613/watch"
