"""question search index

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_question_version_body_fts",
        "question_version",
        [sa.text("to_tsvector('simple', body)")],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_question_version_body_fts", table_name="question_version")
