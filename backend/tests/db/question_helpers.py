"""Clean-up for tests that create questions (locked versions can't be deleted by the app)."""

import uuid

from sqlalchemy import delete, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.models import AuthToken, RefreshToken
from app.platform.models import Institution
from app.questions.models import Question, QuestionOption, QuestionVersion
from app.users.models import User


async def purge_institutions(migrator_engine: AsyncEngine, ids: list[uuid.UUID]) -> None:
    """Delete these institutions with their users and questions, locked versions included.

    The table owner switches the lock triggers off inside this one transaction. DDL is
    transactional in Postgres, so the triggers are never off for anyone else.
    """
    if not ids:
        return
    async with migrator_engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE question_version DISABLE TRIGGER question_version_locked")
        )
        await conn.execute(
            text("ALTER TABLE question_option DISABLE TRIGGER question_option_locked")
        )
        await conn.execute(
            update(Question).where(Question.institution_id.in_(ids)).values(current_version_id=None)
        )
        for model in (QuestionOption, QuestionVersion, Question, AuthToken, RefreshToken, User):
            await conn.execute(delete(model).where(model.institution_id.in_(ids)))
        await conn.execute(delete(Institution).where(Institution.id.in_(ids)))
        await conn.execute(
            text("ALTER TABLE question_option ENABLE TRIGGER question_option_locked")
        )
        await conn.execute(
            text("ALTER TABLE question_version ENABLE TRIGGER question_version_locked")
        )
