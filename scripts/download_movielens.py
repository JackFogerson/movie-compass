import argparse
from pathlib import Path

from ingestion.movielens.download import MOVIELENS_32M_URL, download_movielens


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and verify MovieLens 32M")
    parser.add_argument("--url", default=MOVIELENS_32M_URL)
    return parser.parse_args()

if __name__ == "__main__":
    result = download_movielens(Path("data/raw"), url=parse_args().url)
    print(f"Dataset: {result.dataset_dir}")
    print(f"Downloaded: {result.downloaded}")
    print(f"SHA-256: {result.sha256}")
