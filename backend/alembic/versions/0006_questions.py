"""questions

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


REFUSE_LOCKED_VERSION = """
CREATE FUNCTION refuse_locked_question_version() RETURNS trigger AS $$
BEGIN
    IF OLD.is_locked THEN
        RAISE EXCEPTION 'question version % is locked', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql
"""

REFUSE_LOCKED_OPTION = """
CREATE FUNCTION refuse_option_of_locked_version() RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM question_version v
        WHERE v.is_locked
          AND v.id IN (
              CASE WHEN TG_OP <> 'INSERT' THEN OLD.version_id END,
              CASE WHEN TG_OP <> 'DELETE' THEN NEW.version_id END
          )
    ) THEN
        RAISE EXCEPTION 'question version is locked: its options cannot change'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.create_table(
        "question",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("visibility", sa.String(length=16), server_default="PRIVATE", nullable=False),
        sa.Column("tags", sa.ARRAY(sa.String(length=50)), server_default="{}", nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "type IN ('MCQ', 'MSQ', 'TRUE_FALSE', 'DESCRIPTIVE', 'CODING')",
            name=op.f("ck_question_type"),
        ),
        sa.CheckConstraint(
            "visibility IN ('PRIVATE', 'INSTITUTION')", name=op.f("ck_question_visibility")
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_question_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["user.id"], name=op.f("fk_question_owner_id_user"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question")),
    )
    op.create_index(
        op.f("ix_question_institution_id"), "question", ["institution_id"], unique=False
    )
    op.create_index(op.f("ix_question_owner_id"), "question", ["owner_id"], unique=False)
    op.create_index("ix_question_tags", "question", ["tags"], unique=False, postgresql_using="gin")
    op.create_table(
        "question_version",
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.SmallInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("points", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column(
            "negative_marks", sa.Numeric(precision=6, scale=2), server_default="0", nullable=False
        ),
        sa.Column("msq_scoring", sa.String(length=16), nullable=True),
        sa.Column("max_answer_length", sa.Integer(), nullable=True),
        sa.Column("rubric", sa.Text(), nullable=True),
        sa.Column("is_locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "msq_scoring IS NULL OR msq_scoring IN ('ALL_OR_NOTHING', 'PARTIAL')",
            name=op.f("ck_question_version_msq_scoring"),
        ),
        sa.CheckConstraint(
            "max_answer_length IS NULL OR max_answer_length BETWEEN 1 AND 20000",
            name=op.f("ck_question_version_max_answer_length_range"),
        ),
        sa.CheckConstraint(
            "negative_marks >= 0", name=op.f("ck_question_version_negative_marks_not_negative")
        ),
        sa.CheckConstraint("points > 0", name=op.f("ck_question_version_points_positive")),
        sa.CheckConstraint("version_no >= 1", name=op.f("ck_question_version_version_no_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user.id"],
            name=op.f("fk_question_version_created_by_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_question_version_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["question.id"],
            name=op.f("fk_question_version_question_id_question"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question_version")),
        sa.UniqueConstraint(
            "question_id", "version_no", name=op.f("uq_question_version_question_id_version_no")
        ),
    )
    op.create_index(
        op.f("ix_question_version_institution_id"),
        "question_version",
        ["institution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_question_version_question_id"), "question_version", ["question_id"], unique=False
    )
    op.create_table(
        "question_option",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("order_index", sa.SmallInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_question_option_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["question_version.id"],
            name=op.f("fk_question_option_version_id_question_version"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question_option")),
        sa.UniqueConstraint(
            "version_id", "order_index", name=op.f("uq_question_option_version_id_order_index")
        ),
    )
    op.create_index(
        op.f("ix_question_option_institution_id"),
        "question_option",
        ["institution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_question_option_version_id"), "question_option", ["version_id"], unique=False
    )

    # question <-> question_version point at each other, so this one is added after both exist.
    op.create_foreign_key(
        op.f("fk_question_current_version_id_question_version"),
        "question",
        "question_version",
        ["current_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # A locked version (used by a published exam) and its options can never change again, even
    # through a bug or a hand-written query (architecture D-11). Locking itself is allowed.
    op.execute(REFUSE_LOCKED_VERSION)
    op.execute(REFUSE_LOCKED_OPTION)
    op.execute(
        "CREATE TRIGGER question_version_locked BEFORE UPDATE OR DELETE ON question_version"
        " FOR EACH ROW EXECUTE FUNCTION refuse_locked_question_version()"
    )
    op.execute(
        "CREATE TRIGGER question_option_locked BEFORE INSERT OR UPDATE OR DELETE"
        " ON question_option FOR EACH ROW EXECUTE FUNCTION refuse_option_of_locked_version()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER question_option_locked ON question_option")
    op.execute("DROP TRIGGER question_version_locked ON question_version")
    op.execute("DROP FUNCTION refuse_option_of_locked_version()")
    op.execute("DROP FUNCTION refuse_locked_question_version()")
    op.drop_constraint(
        op.f("fk_question_current_version_id_question_version"), "question", type_="foreignkey"
    )
    op.drop_index(op.f("ix_question_option_version_id"), table_name="question_option")
    op.drop_index(op.f("ix_question_option_institution_id"), table_name="question_option")
    op.drop_table("question_option")
    op.drop_index(op.f("ix_question_version_question_id"), table_name="question_version")
    op.drop_index(op.f("ix_question_version_institution_id"), table_name="question_version")
    op.drop_table("question_version")
    op.drop_index("ix_question_tags", table_name="question", postgresql_using="gin")
    op.drop_index(op.f("ix_question_owner_id"), table_name="question")
    op.drop_index(op.f("ix_question_institution_id"), table_name="question")
    op.drop_table("question")
