from app.services.certifications import certification_bucket, us_certification


def test_us_certification_prefers_theatrical_release() -> None:
    details = {
        "release_dates": {
            "results": [
                {
                    "iso_3166_1": "US",
                    "release_dates": [
                        {"type": 4, "certification": "PG-13"},
                        {"type": 3, "certification": "R"},
                    ],
                }
            ]
        }
    }

    assert us_certification(details) == "R"
    assert certification_bucket("R") == "r"


def test_certification_supports_tv_and_unknown_buckets() -> None:
    details = {"content_ratings": {"results": [{"iso_3166_1": "US", "rating": "TV-MA"}]}}

    assert us_certification(details) == "TV-MA"
    assert certification_bucket("TV-MA") == "other"
    assert certification_bucket(None) == "unknown"
