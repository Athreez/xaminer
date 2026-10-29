"""attempts

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exam_attempt",
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("exam_version_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="IN_PROGRESS", nullable=False),
        sa.Column("grading_status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shuffle_seed", sa.BigInteger(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra_minutes", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("is_preview", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
            "grading_status IN ('PENDING', 'AWAITING_CODING', 'AWAITING_MANUAL', 'COMPLETE')",
            name=op.f("ck_exam_attempt_grading_status"),
        ),
        sa.CheckConstraint(
            "status IN ('IN_PROGRESS', 'SUBMITTED', 'AUTO_SUBMITTED', 'VOIDED')",
            name=op.f("ck_exam_attempt_status"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('SUBMITTED', 'AUTO_SUBMITTED') OR submitted_at IS NOT NULL",
            name=op.f("ck_exam_attempt_submitted_has_time"),
        ),
        sa.CheckConstraint(
            "deadline_at > started_at", name=op.f("ck_exam_attempt_deadline_after_start")
        ),
        sa.CheckConstraint(
            "extra_minutes BETWEEN 0 AND 600", name=op.f("ck_exam_attempt_extra_minutes_range")
        ),
        sa.ForeignKeyConstraint(
            ["exam_id"], ["exam.id"], name=op.f("fk_exam_attempt_exam_id_exam"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["exam_version_id"],
            ["exam_version.id"],
            name=op.f("fk_exam_attempt_exam_version_id_exam_version"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_exam_attempt_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["user.id"],
            name=op.f("fk_exam_attempt_student_id_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_attempt")),
    )
    op.create_index(
        "ix_exam_attempt_exam_id_status", "exam_attempt", ["exam_id", "status"], unique=False
    )
    op.create_index(
        op.f("ix_exam_attempt_institution_id"), "exam_attempt", ["institution_id"], unique=False
    )
    op.create_index(
        "ix_exam_attempt_open_deadline",
        "exam_attempt",
        ["deadline_at"],
        unique=False,
        postgresql_where=sa.text("status = 'IN_PROGRESS'"),
    )
    op.create_index(
        op.f("ix_exam_attempt_student_id"), "exam_attempt", ["student_id"], unique=False
    )
    op.create_index(
        "uq_exam_attempt_one_active",
        "exam_attempt",
        ["exam_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'VOIDED'"),
    )
    op.create_table(
        "answer",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("exam_question_id", sa.Uuid(), nullable=False),
        sa.Column("selected_option_ids", postgresql.ARRAY(sa.Uuid()), nullable=True),
        sa.Column("text_answer", sa.Text(), nullable=True),
        sa.Column("client_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("auto_score", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("manual_score", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("score", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("graded_by", sa.Uuid(), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
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
            "client_revision >= 0", name=op.f("ck_answer_client_revision_not_negative")
        ),
        sa.CheckConstraint(
            "text_answer IS NULL OR char_length(text_answer) <= 65536",
            name=op.f("ck_answer_text_answer_length"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["exam_attempt.id"],
            name=op.f("fk_answer_attempt_id_exam_attempt"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exam_question_id"],
            ["exam_question.id"],
            name=op.f("fk_answer_exam_question_id_exam_question"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["graded_by"], ["user.id"], name=op.f("fk_answer_graded_by_user"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_answer_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attempt_id", "exam_question_id", name=op.f("pk_answer")),
    )
    op.create_index(op.f("ix_answer_institution_id"), "answer", ["institution_id"], unique=False)
    op.create_table(
        "attempt_question",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("exam_question_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("option_order", postgresql.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column(
            "marked_for_review", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("position >= 1", name=op.f("ck_attempt_question_position_positive")),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["exam_attempt.id"],
            name=op.f("fk_attempt_question_attempt_id_exam_attempt"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exam_question_id"],
            ["exam_question.id"],
            name=op.f("fk_attempt_question_exam_question_id_exam_question"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_attempt_question_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attempt_question")),
        sa.UniqueConstraint(
            "attempt_id",
            "exam_question_id",
            name=op.f("uq_attempt_question_attempt_id_exam_question_id"),
        ),
        sa.UniqueConstraint(
            "attempt_id", "position", name=op.f("uq_attempt_question_attempt_id_position")
        ),
    )
    op.create_index(
        op.f("ix_attempt_question_attempt_id"), "attempt_question", ["attempt_id"], unique=False
    )
    op.create_index(
        op.f("ix_attempt_question_institution_id"),
        "attempt_question",
        ["institution_id"],
        unique=False,
    )
    op.create_table(
        "code_draft",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("exam_question_id", sa.Uuid(), nullable=False),
        sa.Column("language_key", sa.String(length=32), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("client_revision", sa.Integer(), server_default="0", nullable=False),
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
            "char_length(source) <= 262144", name=op.f("ck_code_draft_source_length")
        ),
        sa.CheckConstraint(
            "client_revision >= 0", name=op.f("ck_code_draft_client_revision_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["exam_attempt.id"],
            name=op.f("fk_code_draft_attempt_id_exam_attempt"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exam_question_id"],
            ["exam_question.id"],
            name=op.f("fk_code_draft_exam_question_id_exam_question"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_code_draft_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["language_key"],
            ["language.key"],
            name=op.f("fk_code_draft_language_key_language"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "attempt_id", "exam_question_id", "language_key", name=op.f("pk_code_draft")
        ),
    )
    op.create_index(
        op.f("ix_code_draft_institution_id"), "code_draft", ["institution_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_code_draft_institution_id"), table_name="code_draft")
    op.drop_table("code_draft")
    op.drop_index(op.f("ix_attempt_question_institution_id"), table_name="attempt_question")
    op.drop_index(op.f("ix_attempt_question_attempt_id"), table_name="attempt_question")
    op.drop_table("attempt_question")
    op.drop_index(op.f("ix_answer_institution_id"), table_name="answer")
    op.drop_table("answer")
    op.drop_index(
        "uq_exam_attempt_one_active",
        table_name="exam_attempt",
        postgresql_where=sa.text("status <> 'VOIDED'"),
    )
    op.drop_index(op.f("ix_exam_attempt_student_id"), table_name="exam_attempt")
    op.drop_index(
        "ix_exam_attempt_open_deadline",
        table_name="exam_attempt",
        postgresql_where=sa.text("status = 'IN_PROGRESS'"),
    )
    op.drop_index(op.f("ix_exam_attempt_institution_id"), table_name="exam_attempt")
    op.drop_index("ix_exam_attempt_exam_id_status", table_name="exam_attempt")
    op.drop_table("exam_attempt")
