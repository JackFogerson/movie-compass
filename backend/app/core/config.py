from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://movie:movie@localhost:5432/movie_recommender"
    tmdb_api_key: str | None = None
    openai_api_key: str | None = None
    data_dir: Path = Field(default=Path("data"))
    ml_artifacts_dir: Path = Field(default=Path("ml/artifacts"))
    tmdb_cache_ttl_seconds: int = 2_592_000

    @property
    def raw_data_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_data_dir(self) -> Path:
        return self.data_dir / "processed"


@lru_cache
def get_settings() -> Settings:
    return Settings()
