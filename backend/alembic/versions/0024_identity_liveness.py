"""identity and liveness

Revision ID: 0024
Revises: 0023
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = (
    "'FULLSCREEN_EXIT', 'TAB_SWITCH', 'PASTE_BLOCKED', 'MULTIPLE_SCREENS', 'FACE_ABSENT', "
    "'MULTIPLE_FACES', 'GAZE_AWAY', 'VOICE_DETECTED', 'SCREEN_SHARE_STOPPED', 'SIGNAL_LOST', "
    "'PHONE_DETECTED', 'BOOK_DETECTED'"
)
PURPOSES = "'EVENT', 'SPOT_CHECK', 'PERIODIC', 'LEFT_PAGE'"


def _check(table: str, name: str, column: str, values: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, f"{column} IN ({values})")


def upgrade() -> None:
    _check("proctoring_event", "kind", "kind", KINDS + ", 'IDENTITY_MISMATCH', 'LIVENESS_FAILED'")
    _check("proctoring_capture", "purpose", "purpose", PURPOSES + ", 'REFERENCE'")


def downgrade() -> None:
    op.execute("DELETE FROM proctoring_capture WHERE purpose = 'REFERENCE'")
    op.execute(
        "DELETE FROM proctoring_event WHERE kind IN ('IDENTITY_MISMATCH', 'LIVENESS_FAILED')"
    )
    _check("proctoring_capture", "purpose", "purpose", PURPOSES)
    _check("proctoring_event", "kind", "kind", KINDS)
