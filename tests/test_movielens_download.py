import hashlib
from pathlib import Path

import pytest

from ingestion.movielens.download import dataset_is_complete, verify_dataset_checksums


def _write_dataset(path: Path) -> dict[str, str]:
    path.mkdir()
    expected = {}
    for name, content in {
        "links.csv": b"links\n",
        "movies.csv": b"movies\n",
        "ratings.csv": b"ratings\n",
        "tags.csv": b"tags\n",
    }.items():
        (path / name).write_bytes(content)
        expected[name] = hashlib.md5(content, usedforsecurity=False).hexdigest()
    return expected


def test_complete_dataset_passes_checksum_verification(tmp_path: Path) -> None:
    dataset = tmp_path / "ml-32m"
    expected = _write_dataset(dataset)

    assert dataset_is_complete(dataset)
    assert verify_dataset_checksums(dataset, expected) == expected


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    dataset = tmp_path / "ml-32m"
    expected = _write_dataset(dataset)
    (dataset / "ratings.csv").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch for ratings.csv"):
        verify_dataset_checksums(dataset, expected)


def test_dataset_without_tags_is_incomplete(tmp_path: Path) -> None:
    dataset = tmp_path / "ml-32m"
    _write_dataset(dataset)
    (dataset / "tags.csv").unlink()

    assert not dataset_is_complete(dataset)
