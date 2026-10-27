"""user groups

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_group",
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_user_group_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_group")),
        sa.UniqueConstraint(
            "institution_id", "name", name=op.f("uq_user_group_institution_id_name")
        ),
    )
    op.create_index(
        op.f("ix_user_group_institution_id"), "user_group", ["institution_id"], unique=False
    )
    op.create_table(
        "user_group_member",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["user_group.id"],
            name=op.f("fk_user_group_member_group_id_user_group"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_user_group_member_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name=op.f("fk_user_group_member_user_id_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("group_id", "user_id", name=op.f("pk_user_group_member")),
    )
    op.create_index(
        op.f("ix_user_group_member_institution_id"),
        "user_group_member",
        ["institution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_group_member_user_id"), "user_group_member", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_group_member_user_id"), table_name="user_group_member")
    op.drop_index(op.f("ix_user_group_member_institution_id"), table_name="user_group_member")
    op.drop_table("user_group_member")
    op.drop_index(op.f("ix_user_group_institution_id"), table_name="user_group")
    op.drop_table("user_group")
