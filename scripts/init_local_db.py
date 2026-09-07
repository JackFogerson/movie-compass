from app.core.config import get_settings
from app.db import models  # noqa: F401
from app.db.base import Base
from sqlalchemy import create_engine


def main() -> None:
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        raise RuntimeError("Local schema initialization is only for SQLite; use Alembic otherwise")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.processed_data_dir.mkdir(parents=True, exist_ok=True)
    for name in ("tmdb-rich-details.json", "display-metadata.json"):
        cache = settings.processed_data_dir / name
        if not cache.exists():
            cache.write_text("{}\n", encoding="utf-8")
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    print(f"Initialized local database: {settings.database_url}")


if __name__ == "__main__":
    main()
