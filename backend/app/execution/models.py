"""Code execution records (TECHNICAL_ARCHITECTURE.md § 5, "Code execution"; PRD EXE-02..09).

`code_run` (Run Code, public test cases only, never graded) and `coding_submission` (official,
graded) are separate tables on purpose: different rules and lifetimes, and mixing them is how
hidden tests leak or practice runs get graded.

An evaluation, or a code run, is one execution job: its id travels as the job id. It starts
QUEUED; the result consumer locks the row and only ever handles a QUEUED one, so a result that
arrives twice changes nothing the second time.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin
from domain_core.coding_score import CaseOutcome, Verdict

RUN_STATUSES = ("QUEUED", "COMPLETED", "FAILED")
SUBMISSION_STATUSES = ("QUEUED", "EVALUATED", "FAILED")
EVALUATION_STATUSES = ("QUEUED", "DONE", "FAILED")
VERDICTS = tuple(v.value for v in Verdict)
OUTCOMES = tuple(o.value for o in CaseOutcome)
MAX_SOURCE = 262_144  # characters, like code drafts


class CodeRun(IdMixin, TenantMixin, Base):
    """A "Run Code" (EXE-02, EXE-03): public cases or the student's own input. Never graded.
    `results` holds only what the student may see. Deleted after 24 hours."""

    __tablename__ = "code_run"
    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES}", name="status"),
        CheckConstraint(f"char_length(source) <= {MAX_SOURCE}", name="source_length"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_attempt.id", ondelete="CASCADE"), index=True
    )
    exam_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_question.id", ondelete="RESTRICT")
    )
    language_key: Mapped[str] = mapped_column(
        String(32), ForeignKey("language.key", ondelete="RESTRICT")
    )
    source: Mapped[str] = mapped_column(Text)
    custom_input: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), server_default="QUEUED")
    compile_output: Mapped[str | None] = mapped_column(Text)
    results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]


class CodingSubmission(IdMixin, TenantMixin, Base):
    """An official, graded submission (EXE-04..06). `is_auto`: the last draft, submitted when the
    attempt ended (not counted against the limit). `is_counted`: the one that gives the score."""

    __tablename__ = "coding_submission"
    __table_args__ = (
        UniqueConstraint("attempt_id", "exam_question_id", "submission_no"),
        CheckConstraint(f"status IN {SUBMISSION_STATUSES}", name="status"),
        CheckConstraint("submission_no >= 1", name="submission_no_positive"),
        CheckConstraint(f"char_length(source) <= {MAX_SOURCE}", name="source_length"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exam_attempt.id", ondelete="CASCADE"))
    exam_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_question.id", ondelete="RESTRICT")
    )
    submission_no: Mapped[int] = mapped_column(SmallInteger)
    language_key: Mapped[str] = mapped_column(
        String(32), ForeignKey("language.key", ondelete="RESTRICT")
    )
    source: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), server_default="QUEUED")
    is_counted: Mapped[bool] = mapped_column(server_default=text("false"))
    is_auto: Mapped[bool] = mapped_column(server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CodingEvaluation(IdMixin, TenantMixin, Base):
    """One grading of a submission (re-evaluation adds another). INTERNAL_ERROR has no score:
    the platform failing is never a grade (EXE-08)."""

    __tablename__ = "coding_evaluation"
    __table_args__ = (
        UniqueConstraint("submission_id", "evaluation_no"),
        CheckConstraint(f"status IN {EVALUATION_STATUSES}", name="status"),
        CheckConstraint(f"verdict IS NULL OR verdict IN {VERDICTS}", name="verdict"),
        CheckConstraint("evaluation_no >= 1", name="evaluation_no_positive"),
        CheckConstraint("score IS NULL OR score BETWEEN 0 AND max_score", name="score_range"),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coding_submission.id", ondelete="CASCADE")
    )
    evaluation_no: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    status: Mapped[str] = mapped_column(String(12), server_default="QUEUED")
    verdict: Mapped[str | None] = mapped_column(String(24))
    passed_weight: Mapped[int | None] = mapped_column(Integer)
    total_weight: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    max_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    compile_output: Mapped[str | None] = mapped_column(Text)
    image_digest: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    evaluated_at: Mapped[datetime | None]


class TestCaseResult(IdMixin, TenantMixin, Base):
    """How one test case went in one evaluation, with the weight it carried (per-case pass rates,
    re-evaluation). Teachers only: hidden cases' outputs never reach a student."""

    __tablename__ = "test_case_result"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "test_case_id"),
        CheckConstraint(f"outcome IN {OUTCOMES}", name="outcome"),
    )
    __test__ = False  # not a pytest test class, despite the name

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coding_evaluation.id", ondelete="CASCADE")
    )
    test_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_case.id", ondelete="CASCADE"), index=True
    )
    weight: Mapped[int] = mapped_column(SmallInteger)
    outcome: Mapped[str] = mapped_column(String(24))
    time_ms: Mapped[int] = mapped_column(Integer)
    memory_kb: Mapped[int | None] = mapped_column(Integer)
    stdout: Mapped[str] = mapped_column(Text)  # what the program printed (truncated)
    stderr: Mapped[str] = mapped_column(Text)
