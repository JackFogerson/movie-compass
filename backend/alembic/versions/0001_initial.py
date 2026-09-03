"""Initial movie, user, interaction, embedding, and mapping schema."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "movies",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tmdb_id", sa.Integer()),
        sa.Column("imdb_id", sa.String(16)),
        sa.Column("movielens_id", sa.Integer()),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("original_title", sa.String(500)),
        sa.Column("release_date", sa.Date()),
        sa.Column("year", sa.Integer()),
        sa.Column("overview", sa.Text()),
        sa.Column("runtime", sa.Integer()),
        sa.Column("original_language", sa.String(16)),
        sa.Column("popularity", sa.Numeric(12, 4)),
        sa.Column("tmdb_vote_average", sa.Numeric(5, 3)),
        sa.Column("tmdb_vote_count", sa.Integer()),
        sa.Column("poster_path", sa.String(500)),
        sa.Column("backdrop_path", sa.String(500)),
        sa.Column("adult", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(64)),
        sa.Column("metadata_last_updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tmdb_id"),
        sa.UniqueConstraint("imdb_id"),
        sa.UniqueConstraint("movielens_id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "user_movie_interactions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "movie_id",
            sa.BigInteger(),
            sa.ForeignKey("movies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.Numeric(2, 1)),
        sa.Column("liked", sa.Boolean()),
        sa.Column("watched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("watched_date", sa.Date()),
        sa.Column("rewatch_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_text", sa.Text()),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column(
            "imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "movie_id", name="uq_user_movie_interaction"),
    )
    op.create_table(
        "movie_embeddings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "movie_id",
            sa.BigInteger(),
            sa.ForeignKey("movies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding_type", sa.String(100), nullable=False),
        sa.Column("embedding", Vector()),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("movie_id", "embedding_type", "embedding_model"),
    )
    op.create_table(
        "import_mappings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_key", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("year", sa.Integer()),
        sa.Column("movie_id", sa.BigInteger(), sa.ForeignKey("movies.id")),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("candidates_json", sa.Text()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("source", "source_key", name="uq_import_source_key"),
    )


def downgrade() -> None:
    for table in (
        "import_mappings",
        "movie_embeddings",
        "user_movie_interactions",
        "users",
        "movies",
    ):
        op.drop_table(table)
