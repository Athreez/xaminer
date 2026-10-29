"""runner images version 2: /work owned by the runner user, temporary files in /tmp

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEYS = ("cpp17", "java21", "python312", "node22")
language = sa.table("language", sa.column("key", sa.String), sa.column("image", sa.String))


def _tag(version: int) -> None:
    for key in KEYS:
        op.execute(
            language.update()
            .where(language.c.key == key)
            .values(image=f"xaminer-runner-{key}:{version}")
        )


def upgrade() -> None:
    _tag(2)


def downgrade() -> None:
    _tag(1)
