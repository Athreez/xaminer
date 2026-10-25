"""users and auth tokens

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="INVITED", nullable=False),
        sa.Column("roll_no", sa.String(length=64), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("failed_logins", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("role IN ('ADMIN', 'TEACHER', 'STUDENT')", name=op.f("ck_user_role")),
        sa.CheckConstraint(
            "status <> 'ACTIVE' OR password_hash IS NOT NULL",
            name=op.f("ck_user_active_has_password"),
        ),
        sa.CheckConstraint(
            "status IN ('INVITED', 'ACTIVE', 'DEACTIVATED')", name=op.f("ck_user_status")
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_user_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user")),
        sa.UniqueConstraint("institution_id", "email", name=op.f("uq_user_institution_id_email")),
    )
    op.create_index(op.f("ix_user_institution_id"), "user", ["institution_id"], unique=False)
    op.create_index(
        "ix_user_institution_id_role_status",
        "user",
        ["institution_id", "role", "status"],
        unique=False,
    )
    op.create_index(
        "uq_user_institution_id_roll_no",
        "user",
        ["institution_id", "roll_no"],
        unique=True,
        postgresql_where=sa.text("roll_no IS NOT NULL"),
    )
    op.create_table(
        "auth_token",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("purpose IN ('INVITE', 'RESET')", name=op.f("ck_auth_token_purpose")),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_auth_token_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_auth_token_user_id_user"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_token")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_token_token_hash")),
    )
    op.create_index(
        op.f("ix_auth_token_institution_id"), "auth_token", ["institution_id"], unique=False
    )
    op.create_index(op.f("ix_auth_token_user_id"), "auth_token", ["user_id"], unique=False)
    op.create_table(
        "refresh_token",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
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
            name=op.f("fk_refresh_token_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_refresh_token_user_id_user"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_token")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_token_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_token_family_id"), "refresh_token", ["family_id"], unique=False
    )
    op.create_index(
        op.f("ix_refresh_token_institution_id"), "refresh_token", ["institution_id"], unique=False
    )
    op.create_index(op.f("ix_refresh_token_user_id"), "refresh_token", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_refresh_token_user_id"), table_name="refresh_token")
    op.drop_index(op.f("ix_refresh_token_institution_id"), table_name="refresh_token")
    op.drop_index(op.f("ix_refresh_token_family_id"), table_name="refresh_token")
    op.drop_table("refresh_token")
    op.drop_index(op.f("ix_auth_token_user_id"), table_name="auth_token")
    op.drop_index(op.f("ix_auth_token_institution_id"), table_name="auth_token")
    op.drop_table("auth_token")
    op.drop_index(
        "uq_user_institution_id_roll_no",
        table_name="user",
        postgresql_where=sa.text("roll_no IS NOT NULL"),
    )
    op.drop_index("ix_user_institution_id_role_status", table_name="user")
    op.drop_index(op.f("ix_user_institution_id"), table_name="user")
    op.drop_table("user")
