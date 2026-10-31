"""proctoring pictures

Revision ID: 0022
Revises: 0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "proctoring_capture",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("purpose", sa.String(length=12), nullable=False),
        sa.Column("event_client_id", sa.Uuid(), nullable=True),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("kind IN ('CAMERA', 'SCREEN')", name=op.f("ck_proctoring_capture_kind")),
        sa.CheckConstraint(
            "purpose IN ('EVENT', 'SPOT_CHECK', 'PERIODIC', 'LEFT_PAGE')",
            name=op.f("ck_proctoring_capture_purpose"),
        ),
        sa.CheckConstraint(
            "(purpose = 'EVENT') = (event_client_id IS NOT NULL)",
            name=op.f("ck_proctoring_capture_event_has_id"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["exam_attempt.id"],
            name=op.f("fk_proctoring_capture_attempt_id_exam_attempt"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_proctoring_capture_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proctoring_capture")),
        sa.UniqueConstraint(
            "attempt_id", "client_id", name=op.f("uq_proctoring_capture_attempt_id_client_id")
        ),
    )
    op.create_index(op.f("ix_proctoring_capture_attempt_id"), "proctoring_capture", ["attempt_id"])
    op.create_index(
        op.f("ix_proctoring_capture_institution_id"), "proctoring_capture", ["institution_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_proctoring_capture_institution_id"), table_name="proctoring_capture")
    op.drop_index(op.f("ix_proctoring_capture_attempt_id"), table_name="proctoring_capture")
    op.drop_table("proctoring_capture")
