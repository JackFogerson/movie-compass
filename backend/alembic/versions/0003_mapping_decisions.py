"""Add immutable manual mapping decision audit records."""

import sqlalchemy as sa
from alembic import op

revision = "0003_mapping_decisions"
down_revision = "0002_import_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mapping_decisions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "mapping_id",
            sa.BigInteger(),
            sa.ForeignKey("import_mappings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("previous_status", sa.String(30), nullable=False),
        sa.Column("tmdb_id", sa.Integer()),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_mapping_decisions_mapping_id", "mapping_decisions", ["mapping_id"])


def downgrade() -> None:
    op.drop_table("mapping_decisions")
