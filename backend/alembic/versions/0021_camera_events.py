"""camera events

Revision ID: 0021
Revises: 0020
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "('FULLSCREEN_EXIT', 'TAB_SWITCH', 'PASTE_BLOCKED', 'MULTIPLE_SCREENS')"
NEW = (
    "('FULLSCREEN_EXIT', 'TAB_SWITCH', 'PASTE_BLOCKED', 'MULTIPLE_SCREENS', 'FACE_ABSENT', "
    "'MULTIPLE_FACES', 'GAZE_AWAY', 'VOICE_DETECTED', 'SCREEN_SHARE_STOPPED', 'SIGNAL_LOST')"
)


def _kinds(kinds: str) -> None:
    op.drop_constraint(op.f("ck_proctoring_event_kind"), "proctoring_event", type_="check")
    op.create_check_constraint(
        op.f("ck_proctoring_event_kind"), "proctoring_event", f"kind IN {kinds}"
    )


def upgrade() -> None:
    _kinds(NEW)


def downgrade() -> None:
    op.execute(
        "DELETE FROM proctoring_event WHERE kind NOT IN "
        "('FULLSCREEN_EXIT', 'TAB_SWITCH', 'PASTE_BLOCKED', 'MULTIPLE_SCREENS')"
    )
    _kinds(OLD)
