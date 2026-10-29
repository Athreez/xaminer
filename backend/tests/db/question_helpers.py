"""Clean-up for tests that create questions or exams (locked and frozen rows can't be deleted by
the app, by design)."""

import uuid

from sqlalchemy import delete, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import Answer, AttemptQuestion, CodeDraft, ExamAttempt
from app.auth.models import AuthToken, RefreshToken
from app.exams.models import Exam, ExamAssignment, ExamQuestion, ExamVersion
from app.platform.models import Institution
from app.questions.models import Question, QuestionOption, QuestionVersion
from app.users.models import User, UserGroup, UserGroupMember

# (table, trigger) pairs that protect locked or frozen rows.
TRIGGERS = (
    ("question_version", "question_version_locked"),
    ("question_option", "question_option_locked"),
    ("exam_version", "exam_version_frozen"),
    ("coding_config", "coding_config_locked"),
    ("test_case", "test_case_locked"),
    ("reference_solution", "reference_solution_locked"),
)


# Institutions waiting for `purge_queued` at the end of the session.
_queued: list[uuid.UUID] = []


async def purge_institutions(migrator_engine: AsyncEngine, ids: list[uuid.UUID]) -> None:
    """Queue these institutions for deletion when the session ends (see `purge_queued`).

    Deleting needs the protecting triggers off, which locks whole tables; doing it once at the end
    instead of after every test keeps parallel workers from queueing behind each other. Every test
    makes institutions of its own, so leftovers until then are harmless.
    """
    del migrator_engine  # kept in the signature: callers pass the engine they'd purge with
    _queued.extend(ids)


async def purge_queued(migrator_engine: AsyncEngine) -> None:
    """Delete the queued institutions with everything in them, locked and frozen rows included.

    The table owner switches the triggers off inside this one transaction. DDL is
    transactional in Postgres, so the triggers are never off for anyone else.
    """
    ids = list(dict.fromkeys(_queued))
    _queued.clear()
    if not ids:
        return
    async with migrator_engine.begin() as conn:
        for table, trigger in TRIGGERS:
            await conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))
        await conn.execute(
            update(Exam).where(Exam.institution_id.in_(ids)).values(published_version_id=None)
        )
        await conn.execute(
            update(Question).where(Question.institution_id.in_(ids)).values(current_version_id=None)
        )
        for model in (
            CodeDraft,
            Answer,
            AttemptQuestion,
            ExamAttempt,
            ExamAssignment,
            ExamQuestion,
            ExamVersion,
            Exam,
            QuestionOption,
            QuestionVersion,
            Question,
            UserGroupMember,
            UserGroup,
            AuthToken,
            RefreshToken,
            User,
        ):
            await conn.execute(delete(model).where(model.institution_id.in_(ids)))
        await conn.execute(delete(Institution).where(Institution.id.in_(ids)))
        for table, trigger in TRIGGERS:
            await conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}"))
