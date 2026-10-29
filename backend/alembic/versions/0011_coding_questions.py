"""coding questions

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CODING_TABLES = ("coding_config", "test_case", "reference_solution")

# Like question options: the coding part of a locked version (used by a published exam) can never
# change, whatever the code or query (architecture D-11).
REFUSE_LOCKED_CODING = """
CREATE FUNCTION refuse_coding_of_locked_version() RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM question_version v
        WHERE v.is_locked
          AND v.id IN (
              CASE WHEN TG_OP <> 'INSERT' THEN OLD.version_id END,
              CASE WHEN TG_OP <> 'DELETE' THEN NEW.version_id END
          )
    ) THEN
        RAISE EXCEPTION 'question version is locked: its coding setup cannot change'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.create_table(
        "coding_config",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("input_format", sa.Text(), server_default="", nullable=False),
        sa.Column("output_format", sa.Text(), server_default="", nullable=False),
        sa.Column("constraints", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "allowed_languages",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("time_limit_ms", sa.Integer(), server_default="2000", nullable=False),
        sa.Column("memory_limit_mb", sa.SmallInteger(), server_default="256", nullable=False),
        sa.Column("comparison_mode", sa.String(length=16), server_default="TRIM", nullable=False),
        sa.Column("partial_scoring", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("run_code_allowed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("max_submissions", sa.SmallInteger(), server_default="10", nullable=False),
        sa.Column("bundle_key", sa.String(length=255), nullable=True),
        sa.Column(
            "validation_status",
            sa.String(length=16),
            server_default="NEEDS_VALIDATION",
            nullable=False,
        ),
        sa.Column(
            "validation_report",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "comparison_mode IN ('EXACT', 'TRIM', 'TOKEN', 'NUMERIC')",
            name=op.f("ck_coding_config_comparison_mode"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_languages) = 'array'",
            name=op.f("ck_coding_config_allowed_languages_list"),
        ),
        sa.CheckConstraint(
            "validation_status IN ('NEEDS_VALIDATION', 'VALIDATING', 'PASSED', 'FAILED')",
            name=op.f("ck_coding_config_validation_status"),
        ),
        sa.CheckConstraint(
            "max_submissions BETWEEN 1 AND 100", name=op.f("ck_coding_config_max_submissions_range")
        ),
        sa.CheckConstraint(
            "memory_limit_mb BETWEEN 16 AND 512", name=op.f("ck_coding_config_memory_limit_range")
        ),
        sa.CheckConstraint(
            "time_limit_ms BETWEEN 100 AND 10000", name=op.f("ck_coding_config_time_limit_range")
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_coding_config_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["question_version.id"],
            name=op.f("fk_coding_config_version_id_question_version"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("version_id", name=op.f("pk_coding_config")),
    )
    op.create_index(
        op.f("ix_coding_config_institution_id"), "coding_config", ["institution_id"], unique=False
    )
    op.create_table(
        "reference_solution",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("language_key", sa.String(length=32), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "octet_length(source) <= 262144", name=op.f("ck_reference_solution_source_size")
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_reference_solution_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["language_key"],
            ["language.key"],
            name=op.f("fk_reference_solution_language_key_language"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["question_version.id"],
            name=op.f("fk_reference_solution_version_id_question_version"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reference_solution")),
        sa.UniqueConstraint(
            "version_id", "language_key", name=op.f("uq_reference_solution_version_id_language_key")
        ),
    )
    op.create_index(
        op.f("ix_reference_solution_institution_id"),
        "reference_solution",
        ["institution_id"],
        unique=False,
    )
    op.create_table(
        "test_case",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("visibility", sa.String(length=8), server_default="HIDDEN", nullable=False),
        sa.Column("weight", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("expected_output", sa.Text(), nullable=False),
        sa.Column("order_index", sa.SmallInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "visibility IN ('PUBLIC', 'HIDDEN')", name=op.f("ck_test_case_visibility")
        ),
        sa.CheckConstraint(
            "octet_length(expected_output) <= 1048576",
            name=op.f("ck_test_case_expected_output_size"),
        ),
        sa.CheckConstraint("octet_length(input) <= 1048576", name=op.f("ck_test_case_input_size")),
        sa.CheckConstraint("weight BETWEEN 1 AND 1000", name=op.f("ck_test_case_weight_range")),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_test_case_institution_id_institution"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["question_version.id"],
            name=op.f("fk_test_case_version_id_question_version"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_case")),
        sa.UniqueConstraint(
            "version_id",
            "order_index",
            deferrable=True,
            initially="DEFERRED",
            name=op.f("uq_test_case_version_id_order_index"),
        ),
    )
    op.create_index(
        op.f("ix_test_case_institution_id"), "test_case", ["institution_id"], unique=False
    )

    op.execute(REFUSE_LOCKED_CODING)
    for table in CODING_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_locked BEFORE INSERT OR UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION refuse_coding_of_locked_version()"
        )


def downgrade() -> None:
    for table in CODING_TABLES:
        op.execute(f"DROP TRIGGER {table}_locked ON {table}")
    op.execute("DROP FUNCTION refuse_coding_of_locked_version()")
    op.drop_index(op.f("ix_test_case_institution_id"), table_name="test_case")
    op.drop_table("test_case")
    op.drop_index(op.f("ix_reference_solution_institution_id"), table_name="reference_solution")
    op.drop_table("reference_solution")
    op.drop_index(op.f("ix_coding_config_institution_id"), table_name="coding_config")
    op.drop_table("coding_config")
