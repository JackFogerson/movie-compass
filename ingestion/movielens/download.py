from __future__ import annotations

import hashlib
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

MOVIELENS_32M_URL = "https://files.grouplens.org/datasets/movielens/ml-32m.zip"
OFFICIAL_FILE_MD5 = {
    "links.csv": "8f033867bcb4e6be8792b21468b4fa6e",
    "movies.csv": "0df90835c19151f9d819d0822e190797",
    "ratings.csv": "cf12b74f9ad4b94a011f079e26d4270a",
    "tags.csv": "963bf4fa4de6b8901868fddd3eb54567",
}
REQUIRED_FILES = tuple(OFFICIAL_FILE_MD5)


@dataclass(frozen=True)
class DownloadResult:
    archive_path: Path
    dataset_dir: Path
    downloaded: bool
    sha256: str


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    # MD5 is used only to compare the dataset with GroupLens' published checksums.
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_dataset_checksums(
    dataset_dir: Path, expected: dict[str, str] = OFFICIAL_FILE_MD5
) -> dict[str, str]:
    actual: dict[str, str] = {}
    for name, expected_digest in expected.items():
        path = dataset_dir / name
        if not path.is_file():
            raise ValueError(f"MovieLens dataset is missing required file: {path}")
        digest = md5_file(path)
        actual[name] = digest
        if digest.lower() != expected_digest.lower():
            raise ValueError(
                f"MovieLens checksum mismatch for {name}: "
                f"expected {expected_digest}, got {digest}"
            )
    return actual


def dataset_is_complete(dataset_dir: Path) -> bool:
    return all((dataset_dir / name).is_file() for name in REQUIRED_FILES)


def download_movielens(destination: Path, url: str = MOVIELENS_32M_URL) -> DownloadResult:
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "ml-32m.zip"
    dataset_dir = destination / "ml-32m"
    downloaded = False
    if dataset_is_complete(dataset_dir):
        verify_dataset_checksums(dataset_dir)
        return DownloadResult(
            archive, dataset_dir, False, sha256_file(archive) if archive.exists() else ""
        )
    if not archive.exists():
        temporary = archive.with_suffix(".zip.part")
        try:
            with (
                urllib.request.urlopen(url, timeout=60) as response,
                temporary.open("wb") as output,
            ):
                shutil.copyfileobj(response, output)
            temporary.replace(archive)
            downloaded = True
        finally:
            temporary.unlink(missing_ok=True)
    if not zipfile.is_zipfile(archive):
        raise ValueError(f"Downloaded file is not a valid ZIP archive: {archive}")
    with zipfile.ZipFile(archive) as bundle:
        members_by_name: dict[str, list[str]] = {}
        for member in bundle.namelist():
            members_by_name.setdefault(Path(member).name, []).append(member)
        missing = set(REQUIRED_FILES) - set(members_by_name)
        if missing:
            raise ValueError(f"MovieLens archive is missing required files: {sorted(missing)}")
        duplicates = {
            name: members
            for name, members in members_by_name.items()
            if name in REQUIRED_FILES and len(members) != 1
        }
        if duplicates:
            raise ValueError(f"MovieLens archive has duplicate required files: {duplicates}")
        dataset_dir.mkdir(parents=True, exist_ok=True)
        for name in REQUIRED_FILES:
            target = dataset_dir / name
            temporary = target.with_suffix(f"{target.suffix}.part")
            try:
                with (
                    bundle.open(members_by_name[name][0]) as source,
                    temporary.open("wb") as output,
                ):
                    shutil.copyfileobj(source, output)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
    if not dataset_is_complete(dataset_dir):
        raise RuntimeError(
            f"MovieLens extraction did not create a complete dataset at {dataset_dir}"
        )
    verify_dataset_checksums(dataset_dir)
    return DownloadResult(archive, dataset_dir, downloaded, sha256_file(archive))
