"""consent records, screen sharing setting

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_DETECTORS = '\'{"sensitivity": "STANDARD", "gaze": false, "books": false}\'::jsonb'
NEW_DETECTORS = (
    '\'{"sensitivity": "STANDARD", "gaze": false, "books": false, "screen": true}\'::jsonb'
)


def upgrade() -> None:
    op.create_table(
        "consent_record",
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("consent_text_hash", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=8), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('ACCEPTED', 'DECLINED')", name=op.f("ck_consent_record_decision")
        ),
        sa.ForeignKeyConstraint(
            ["exam_id"],
            ["exam.id"],
            name=op.f("fk_consent_record_exam_id_exam"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["user.id"],
            name=op.f("fk_consent_record_student_id_user"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_consent_record_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_record")),
    )
    op.create_index(
        "ix_consent_record_exam_id_student_id", "consent_record", ["exam_id", "student_id"]
    )
    op.create_index(op.f("ix_consent_record_institution_id"), "consent_record", ["institution_id"])
    op.alter_column("exam", "proctoring_detectors", server_default=sa.text(NEW_DETECTORS))


def downgrade() -> None:
    op.alter_column("exam", "proctoring_detectors", server_default=sa.text(OLD_DETECTORS))
    op.drop_index(op.f("ix_consent_record_institution_id"), table_name="consent_record")
    op.drop_index("ix_consent_record_exam_id_student_id", table_name="consent_record")
    op.drop_table("consent_record")
