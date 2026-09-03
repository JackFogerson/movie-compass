from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PRIMARY_KEY_TYPE = BigInteger().with_variant(Integer, "sqlite")


class Movie(Base):
    __tablename__ = "movies"
    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    imdb_id: Mapped[str | None] = mapped_column(String(16), unique=True, index=True)
    movielens_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    original_title: Mapped[str | None] = mapped_column(String(500))
    release_date: Mapped[date | None] = mapped_column(Date)
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    overview: Mapped[str | None] = mapped_column(Text)
    runtime: Mapped[int | None] = mapped_column(Integer)
    original_language: Mapped[str | None] = mapped_column(String(16))
    popularity: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    tmdb_vote_average: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    tmdb_vote_count: Mapped[int | None] = mapped_column(Integer)
    poster_path: Mapped[str | None] = mapped_column(String(500))
    backdrop_path: Mapped[str | None] = mapped_column(String(500))
    adult: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str | None] = mapped_column(String(64))
    metadata_last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserMovieInteraction(Base):
    __tablename__ = "user_movie_interactions"
    __table_args__ = (UniqueConstraint("user_id", "movie_id", name="uq_user_movie_interaction"),)
    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), index=True)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    liked: Mapped[bool | None] = mapped_column(Boolean)
    watched: Mapped[bool] = mapped_column(Boolean, default=False)
    watched_date: Mapped[date | None] = mapped_column(Date)
    rewatch_count: Mapped[int] = mapped_column(Integer, default=0)
    review_text: Mapped[str | None] = mapped_column(Text)
    watchlisted: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(50), default="letterboxd")
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MovieEmbedding(Base):
    __tablename__ = "movie_embeddings"
    __table_args__ = (UniqueConstraint("movie_id", "embedding_type", "embedding_model"),)
    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), index=True)
    embedding_type: Mapped[str] = mapped_column(String(100))
    embedding: Mapped[list[float]] = mapped_column(Vector())
    embedding_model: Mapped[str] = mapped_column(String(200))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ImportMapping(Base):
    __tablename__ = "import_mappings"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "source_key", name="uq_user_import_source_key"),
    )
    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(50))
    source_key: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(String(500))
    year: Mapped[int | None] = mapped_column(Integer)
    movie_id: Mapped[int | None] = mapped_column(ForeignKey("movies.id"))
    status: Mapped[str] = mapped_column(String(30), index=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    candidates_json: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    liked: Mapped[bool | None] = mapped_column(Boolean)
    watched: Mapped[bool] = mapped_column(Boolean, default=False)
    watched_date: Mapped[date | None] = mapped_column(Date)
    rewatch_count: Mapped[int] = mapped_column(Integer, default=0)
    review_text: Mapped[str | None] = mapped_column(Text)
    watchlisted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImportRun(Base):
    __tablename__ = "import_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "archive_sha256", name="uq_import_archive"),
    )
    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(50))
    archive_sha256: Mapped[str] = mapped_column(String(64))
    archive_name: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30))
    report_json: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TmdbSearchCache(Base):
    __tablename__ = "tmdb_search_cache"
    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    query_title: Mapped[str] = mapped_column(String(500))
    query_year: Mapped[int | None] = mapped_column(Integer)
    response_json: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class MappingDecision(Base):
    __tablename__ = "mapping_decisions"
    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True)
    mapping_id: Mapped[int] = mapped_column(
        ForeignKey("import_mappings.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(30))
    previous_status: Mapped[str] = mapped_column(String(30))
    tmdb_id: Mapped[int | None] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
