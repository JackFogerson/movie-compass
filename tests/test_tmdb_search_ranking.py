from ingestion.tmdb.client import rank_title_search_results


def test_full_title_matches_remove_unrelated_single_word_results() -> None:
    results = [
        {"id": 1, "title": "Alice", "adult": True, "popularity": 100},
        {"id": 2, "title": "Sweet Alice", "adult": False},
        {"id": 3, "title": "Alice, Sweet Alice", "adult": False},
        {"id": 4, "title": "An Encounter with Alice", "adult": True},
    ]

    ranked = rank_title_search_results("alice, sweet alice", results)

    assert [item["id"] for item in ranked] == [3, 2]


def test_partial_results_remain_available_when_no_full_title_match_exists() -> None:
    results = [
        {"id": 1, "title": "Alice in Wonderland"},
        {"id": 2, "title": "Sweet Charity"},
    ]

    ranked = rank_title_search_results("Alice Sweet", results)

    assert {item["id"] for item in ranked} == {1, 2}
