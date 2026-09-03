"""Add repeatable Letterboxd imports and durable TMDB search caching."""

import sqlalchemy as sa
from alembic import op

revision = "0002_import_persistence"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_movie_interactions",
        sa.Column("watchlisted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.drop_constraint("uq_import_source_key", "import_mappings", type_="unique")
    op.add_column("import_mappings", sa.Column("user_id", sa.BigInteger(), nullable=True))
    op.add_column("import_mappings", sa.Column("rating", sa.Numeric(2, 1)))
    op.add_column("import_mappings", sa.Column("liked", sa.Boolean()))
    op.add_column(
        "import_mappings",
        sa.Column("watched", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("import_mappings", sa.Column("watched_date", sa.Date()))
    op.add_column(
        "import_mappings",
        sa.Column("rewatch_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("import_mappings", sa.Column("review_text", sa.Text()))
    op.add_column(
        "import_mappings",
        sa.Column("watchlisted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "INSERT INTO users (slug, display_name) VALUES ('default', 'Default User') "
        "ON CONFLICT (slug) DO NOTHING"
    )
    op.execute(
        "UPDATE import_mappings SET user_id = "
        "(SELECT id FROM users WHERE slug = 'default') WHERE user_id IS NULL"
    )
    op.alter_column("import_mappings", "user_id", nullable=False)
    op.create_foreign_key(
        "fk_import_mapping_user",
        "import_mappings",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_user_import_source_key", "import_mappings", ["user_id", "source", "source_key"]
    )
    op.create_index("ix_import_mappings_user_id", "import_mappings", ["user_id"])
    op.create_table(
        "import_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("archive_sha256", sa.String(64), nullable=False),
        sa.Column("archive_name", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "source", "archive_sha256", name="uq_import_archive"),
    )
    op.create_index("ix_import_runs_user_id", "import_runs", ["user_id"])
    op.create_table(
        "tmdb_search_cache",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("cache_key", sa.String(64), nullable=False, unique=True),
        sa.Column("query_title", sa.String(500), nullable=False),
        sa.Column("query_year", sa.Integer()),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tmdb_search_cache_cache_key", "tmdb_search_cache", ["cache_key"])
    op.create_index("ix_tmdb_search_cache_expires_at", "tmdb_search_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_table("tmdb_search_cache")
    op.drop_table("import_runs")
    op.drop_index("ix_import_mappings_user_id", table_name="import_mappings")
    op.drop_constraint("uq_user_import_source_key", "import_mappings", type_="unique")
    op.drop_constraint("fk_import_mapping_user", "import_mappings", type_="foreignkey")
    for column in (
        "watchlisted",
        "review_text",
        "rewatch_count",
        "watched_date",
        "watched",
        "liked",
        "rating",
        "user_id",
    ):
        op.drop_column("import_mappings", column)
    op.create_unique_constraint("uq_import_source_key", "import_mappings", ["source", "source_key"])
    op.drop_column("user_movie_interactions", "watchlisted")
