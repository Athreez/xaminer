"""picture checks

Revision ID: 0023
Revises: 0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = (
    "('FULLSCREEN_EXIT', 'TAB_SWITCH', 'PASTE_BLOCKED', 'MULTIPLE_SCREENS', 'FACE_ABSENT', "
    "'MULTIPLE_FACES', 'GAZE_AWAY', 'VOICE_DETECTED', 'SCREEN_SHARE_STOPPED', 'SIGNAL_LOST')"
)
NEW = OLD[:-1] + ", 'PHONE_DETECTED', 'BOOK_DETECTED')"


def _kinds(kinds: str) -> None:
    op.drop_constraint(op.f("ck_proctoring_event_kind"), "proctoring_event", type_="check")
    op.create_check_constraint(
        op.f("ck_proctoring_event_kind"), "proctoring_event", f"kind IN {kinds}"
    )


def upgrade() -> None:
    _kinds(NEW)
    op.add_column(
        "proctoring_event",
        sa.Column("status", sa.String(length=12), server_default="READY", nullable=False),
    )
    op.add_column("proctoring_event", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column(
        "proctoring_event", sa.Column("check_sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_proctoring_event_status"),
        "proctoring_event",
        "status IN ('PROCESSING', 'READY', 'REJECTED')",
    )
    op.add_column(
        "proctoring_capture",
        sa.Column("check_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "proctoring_capture", sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("proctoring_capture", "checked_at")
    op.drop_column("proctoring_capture", "check_sent_at")
    op.drop_constraint(op.f("ck_proctoring_event_status"), "proctoring_event", type_="check")
    op.drop_column("proctoring_event", "check_sent_at")
    op.drop_column("proctoring_event", "confidence")
    op.drop_column("proctoring_event", "status")
    op.execute("DELETE FROM proctoring_event WHERE kind IN ('PHONE_DETECTED', 'BOOK_DETECTED')")
    _kinds(OLD)
