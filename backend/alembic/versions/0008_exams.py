"""exams

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


REFUSE_CHANGES = """
CREATE FUNCTION refuse_exam_version_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'exam version % is frozen: published exams cannot change', OLD.id
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.create_table(
        "exam",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("instructions", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_min", sa.SmallInteger(), nullable=True),
        sa.Column("navigation_mode", sa.String(length=16), server_default="FREE", nullable=False),
        sa.Column(
            "shuffle_questions", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("shuffle_options", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("run_code_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("release_policy", sa.String(length=16), server_default="MANUAL", nullable=False),
        sa.Column("counted_submission", sa.String(length=8), server_default="BEST", nullable=False),
        sa.Column("pass_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("proctoring_mode", sa.String(length=16), server_default="OFF", nullable=False),
        sa.Column(
            "proctoring_detectors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(
                '\'{"sensitivity": "STANDARD", "gaze": false, "books": false}\'::jsonb'
            ),
            nullable=False,
        ),
        sa.Column("consent_text", sa.Text(), nullable=True),
        sa.Column("published_version_id", sa.Uuid(), nullable=True),
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
            "counted_submission IN ('BEST', 'LAST')", name=op.f("ck_exam_counted_submission")
        ),
        sa.CheckConstraint(
            "navigation_mode IN ('FREE', 'SEQUENTIAL')", name=op.f("ck_exam_navigation_mode")
        ),
        sa.CheckConstraint(
            "proctoring_mode IN ('OFF', 'VIDEO', 'VIDEO_AUDIO')",
            name=op.f("ck_exam_proctoring_mode"),
        ),
        sa.CheckConstraint(
            "release_policy IN ('MANUAL', 'ON_SUBMIT')", name=op.f("ck_exam_release_policy")
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')", name=op.f("ck_exam_status")
        ),
        sa.CheckConstraint("close_at > open_at", name=op.f("ck_exam_window_order")),
        sa.CheckConstraint("duration_min BETWEEN 1 AND 600", name=op.f("ck_exam_duration_range")),
        sa.CheckConstraint(
            "pass_percent BETWEEN 0 AND 100", name=op.f("ck_exam_pass_percent_range")
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_exam_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["user.id"], name=op.f("fk_exam_owner_id_user"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam")),
    )
    op.create_index(op.f("ix_exam_institution_id"), "exam", ["institution_id"], unique=False)
    op.create_index(
        "ix_exam_institution_id_owner_id_status",
        "exam",
        ["institution_id", "owner_id", "status"],
        unique=False,
    )
    op.create_table(
        "exam_assignment",
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by", sa.Uuid(), nullable=False),
        sa.Column("via_group_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assigned_by"],
            ["user.id"],
            name=op.f("fk_exam_assignment_assigned_by_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["exam_id"],
            ["exam.id"],
            name=op.f("fk_exam_assignment_exam_id_exam"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_exam_assignment_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["user.id"],
            name=op.f("fk_exam_assignment_student_id_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["via_group_id"],
            ["user_group.id"],
            name=op.f("fk_exam_assignment_via_group_id_user_group"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_assignment")),
        sa.UniqueConstraint(
            "exam_id", "student_id", name=op.f("uq_exam_assignment_exam_id_student_id")
        ),
    )
    op.create_index(
        op.f("ix_exam_assignment_exam_id"), "exam_assignment", ["exam_id"], unique=False
    )
    op.create_index(
        op.f("ix_exam_assignment_institution_id"),
        "exam_assignment",
        ["institution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_exam_assignment_student_id"), "exam_assignment", ["student_id"], unique=False
    )
    op.create_table(
        "exam_version",
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.SmallInteger(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["exam_id"], ["exam.id"], name=op.f("fk_exam_version_exam_id_exam"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_exam_version_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_version")),
        sa.UniqueConstraint(
            "exam_id", "version_no", name=op.f("uq_exam_version_exam_id_version_no")
        ),
    )
    op.create_index(op.f("ix_exam_version_exam_id"), "exam_version", ["exam_id"], unique=False)
    op.create_index(
        op.f("ix_exam_version_institution_id"), "exam_version", ["institution_id"], unique=False
    )
    op.create_table(
        "exam_question",
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("pinned_version_id", sa.Uuid(), nullable=True),
        sa.Column("order_index", sa.SmallInteger(), nullable=False),
        sa.Column("points", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("negative_marks", sa.Numeric(precision=6, scale=2), nullable=True),
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
            "negative_marks IS NULL OR negative_marks >= 0",
            name=op.f("ck_exam_question_negative_marks_not_negative"),
        ),
        sa.CheckConstraint(
            "order_index >= 0", name=op.f("ck_exam_question_order_index_not_negative")
        ),
        sa.CheckConstraint(
            "points IS NULL OR points > 0", name=op.f("ck_exam_question_points_positive")
        ),
        sa.ForeignKeyConstraint(
            ["exam_id"], ["exam.id"], name=op.f("fk_exam_question_exam_id_exam"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_exam_question_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pinned_version_id"],
            ["question_version.id"],
            name=op.f("fk_exam_question_pinned_version_id_question_version"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["question.id"],
            name=op.f("fk_exam_question_question_id_question"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_question")),
        sa.UniqueConstraint(
            "exam_id",
            "order_index",
            deferrable=True,
            initially="DEFERRED",
            name=op.f("uq_exam_question_exam_id_order_index"),
        ),
        sa.UniqueConstraint(
            "exam_id", "question_id", name=op.f("uq_exam_question_exam_id_question_id")
        ),
    )
    op.create_index(op.f("ix_exam_question_exam_id"), "exam_question", ["exam_id"], unique=False)
    op.create_index(
        op.f("ix_exam_question_institution_id"), "exam_question", ["institution_id"], unique=False
    )
    op.create_index(
        op.f("ix_exam_question_question_id"), "exam_question", ["question_id"], unique=False
    )

    # exam <-> exam_version point at each other, so this one is added after both exist.
    op.create_foreign_key(
        op.f("fk_exam_published_version_id_exam_version"),
        "exam",
        "exam_version",
        ["published_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # A published exam's snapshot never changes and is never deleted (architecture D-11). That
    # also stops a published exam being deleted, because deleting it would cascade here.
    op.execute(REFUSE_CHANGES)
    op.execute(
        "CREATE TRIGGER exam_version_frozen BEFORE UPDATE OR DELETE ON exam_version"
        " FOR EACH ROW EXECUTE FUNCTION refuse_exam_version_change()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER exam_version_frozen ON exam_version")
    op.execute("DROP FUNCTION refuse_exam_version_change()")
    op.drop_constraint(
        op.f("fk_exam_published_version_id_exam_version"), "exam", type_="foreignkey"
    )
    op.drop_index(op.f("ix_exam_question_question_id"), table_name="exam_question")
    op.drop_index(op.f("ix_exam_question_institution_id"), table_name="exam_question")
    op.drop_index(op.f("ix_exam_question_exam_id"), table_name="exam_question")
    op.drop_table("exam_question")
    op.drop_index(op.f("ix_exam_version_institution_id"), table_name="exam_version")
    op.drop_index(op.f("ix_exam_version_exam_id"), table_name="exam_version")
    op.drop_table("exam_version")
    op.drop_index(op.f("ix_exam_assignment_student_id"), table_name="exam_assignment")
    op.drop_index(op.f("ix_exam_assignment_institution_id"), table_name="exam_assignment")
    op.drop_index(op.f("ix_exam_assignment_exam_id"), table_name="exam_assignment")
    op.drop_table("exam_assignment")
    op.drop_index("ix_exam_institution_id_owner_id_status", table_name="exam")
    op.drop_index(op.f("ix_exam_institution_id"), table_name="exam")
    op.drop_table("exam")
