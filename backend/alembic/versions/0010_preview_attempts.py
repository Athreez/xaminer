"""preview attempts

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "exam_attempt",
        sa.Column("preview_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.alter_column("exam_attempt", "exam_version_id", existing_type=sa.UUID(), nullable=True)
    # Every attempt has exactly one copy of the exam: the published version, or (previews only)
    # its own snapshot.
    op.create_check_constraint(
        op.f("ck_exam_attempt_one_exam_copy"),
        "exam_attempt",
        "(exam_version_id IS NULL) <> (preview_snapshot IS NULL)"
        " AND (preview_snapshot IS NULL OR is_preview)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_exam_attempt_one_exam_copy"), "exam_attempt", type_="check")
    # Previews of drafts have no version to fall back to; they are only teachers' test runs.
    op.execute("DELETE FROM exam_attempt WHERE exam_version_id IS NULL AND is_preview")
    op.alter_column("exam_attempt", "exam_version_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("exam_attempt", "preview_snapshot")
