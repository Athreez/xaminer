"""baseline: extensions and the institution table

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Trusted extensions; the migrator may create them because it has CREATE on the database.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")  # case-insensitive emails (user table)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")  # fuzzy name search

    op.create_table(
        "institution",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="ACTIVE", nullable=False),
        sa.Column(
            "evidence_retention_days", sa.SmallInteger(), server_default="30", nullable=False
        ),
        sa.Column("default_consent_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('ACTIVE', 'SUSPENDED')", name=op.f("ck_institution_status")),
        sa.CheckConstraint(
            "evidence_retention_days BETWEEN 7 AND 90", name=op.f("ck_institution_retention_range")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_institution")),
    )


def downgrade() -> None:
    op.drop_table("institution")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS citext")
