"""audit log

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_role", sa.String(length=16), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(
        "ix_audit_log_institution_id_actor_id",
        "audit_log",
        ["institution_id", "actor_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_log_institution_id_created_at",
        "audit_log",
        ["institution_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_log_institution_id_target",
        "audit_log",
        ["institution_id", "target_type", "target_id"],
        unique=False,
    )
    # Append-only by database rule (SECURITY_AND_ACCESS.md § 5.6): the app may add and read
    # entries, never change or remove them.
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM app")


def downgrade() -> None:
    op.drop_index("ix_audit_log_institution_id_target", table_name="audit_log")
    op.drop_index("ix_audit_log_institution_id_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_institution_id_actor_id", table_name="audit_log")
    op.drop_table("audit_log")
