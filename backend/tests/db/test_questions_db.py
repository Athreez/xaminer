"""Question tables and the locked-version trigger (PRD QB-07, architecture D-11).

Runs as the app's own database user, so it proves the rule holds even if application code
tried to change a locked version.
"""

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import SessionFactory, create_session_factory, tenant_session
from app.platform.models import Institution
from app.questions.models import Question, QuestionOption, QuestionVersion
from app.users.models import User
from cli import commands


@pytest.fixture
def factory(app_engine: AsyncEngine) -> SessionFactory:
    return create_session_factory(app_engine)


@pytest.fixture
async def world(factory: SessionFactory, migrator_engine: AsyncEngine) -> AsyncIterator[tuple]:
    college = await commands.create_institution(
        factory, f"Questions DB test {uuid.uuid4().hex[:8]}"
    )
    async with tenant_session(factory, college.id) as s:
        teacher = User(email=f"t{uuid.uuid4().hex[:8]}@abc.edu", full_name="T", role="TEACHER")
        s.add(teacher)
        await s.flush()
        question = Question(owner_id=teacher.id, type="MCQ", tags=["arrays", "easy"])
        s.add(question)
        await s.flush()
        version = QuestionVersion(
            question_id=question.id,
            version_no=1,
            body="What is 2 + 2?",
            points=Decimal("2"),
            created_by=teacher.id,
        )
        s.add(version)
        await s.flush()
        s.add_all(
            QuestionOption(
                version_id=version.id, label=label, is_correct=label == "4", order_index=i
            )
            for i, label in enumerate(["3", "4", "5"])
        )
        question.current_version_id = version.id
        await s.commit()
    yield college, question.id, version.id
    # Locked rows can't be deleted, by design. The table owner switches the triggers off inside
    # this one transaction to clean up; DDL is transactional, so they are never off for others.
    async with migrator_engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE question_version DISABLE TRIGGER question_version_locked")
        )
        await conn.execute(
            text("ALTER TABLE question_option DISABLE TRIGGER question_option_locked")
        )
        await conn.execute(
            text("UPDATE question SET current_version_id = NULL WHERE institution_id = :i"),
            {"i": college.id},
        )
        for model in (QuestionOption, QuestionVersion, Question, User):
            await conn.execute(delete(model).where(model.institution_id == college.id))
        await conn.execute(delete(Institution).where(Institution.id == college.id))
        await conn.execute(
            text("ALTER TABLE question_option ENABLE TRIGGER question_option_locked")
        )
        await conn.execute(
            text("ALTER TABLE question_version ENABLE TRIGGER question_version_locked")
        )


async def lock(factory: SessionFactory, college: Institution, version_id: uuid.UUID) -> None:
    async with tenant_session(factory, college.id) as s:
        await s.execute(
            update(QuestionVersion).where(QuestionVersion.id == version_id).values(is_locked=True)
        )
        await s.commit()


async def refused(factory: SessionFactory, college: Institution, statement) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session(factory, college.id) as s:
        with pytest.raises(DBAPIError) as caught:
            await s.execute(statement)
            await s.flush()
        await s.rollback()
    return str(caught.value)


async def test_unlocked_versions_can_be_edited(factory: SessionFactory, world: tuple) -> None:
    college, _, version_id = world
    async with tenant_session(factory, college.id) as s:
        await s.execute(
            update(QuestionVersion).where(QuestionVersion.id == version_id).values(body="2 + 2 = ?")
        )
        await s.execute(
            update(QuestionOption)
            .where(QuestionOption.version_id == version_id, QuestionOption.order_index == 0)
            .values(label="three")
        )
        await s.commit()


async def test_locked_version_and_its_options_never_change(
    factory: SessionFactory, world: tuple
) -> None:
    college, question_id, version_id = world
    await lock(factory, college, version_id)
    one_version = QuestionVersion.id == version_id
    its_options = QuestionOption.version_id == version_id

    attempts = [
        update(QuestionVersion).where(one_version).values(body="changed"),
        update(QuestionVersion).where(one_version).values(points=Decimal("5")),
        update(QuestionVersion).where(one_version).values(is_locked=False),  # no unlocking
        delete(QuestionVersion).where(one_version),
        update(QuestionOption).where(its_options).values(is_correct=True),
        delete(QuestionOption).where(its_options),
    ]
    for statement in attempts:
        assert "is locked" in await refused(factory, college, statement), statement

    async with tenant_session(factory, college.id) as s:  # adding an option is refused too
        s.add(QuestionOption(version_id=version_id, label="6", is_correct=False, order_index=9))
        with pytest.raises(DBAPIError, match="is locked"):
            await s.flush()

    message = await refused(factory, college, delete(Question).where(Question.id == question_id))
    assert "is locked" in message  # deleting the question would cascade into the version

    async with tenant_session(factory, college.id) as s:
        version = await s.get(QuestionVersion, version_id)
        assert version is not None and version.body == "What is 2 + 2?" and version.is_locked


async def test_a_new_version_is_free_to_edit(factory: SessionFactory, world: tuple) -> None:
    """Editing a used question means adding version 2; the question row itself stays editable."""
    college, question_id, version_id = world
    await lock(factory, college, version_id)
    async with tenant_session(factory, college.id) as s:
        question = await s.get(Question, question_id)
        assert question is not None
        v2 = QuestionVersion(
            question_id=question_id,
            version_no=2,
            body="What is 3 + 3?",
            points=Decimal("2"),
            created_by=question.owner_id,
        )
        s.add(v2)
        await s.flush()
        s.add(QuestionOption(version_id=v2.id, label="6", is_correct=True, order_index=0))
        question.current_version_id = v2.id
        question.tags = ["arrays"]
        await s.commit()
        await s.execute(update(QuestionVersion).where(QuestionVersion.id == v2.id).values(body="x"))
        await s.commit()


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"version_no": 1}, "uq_question_version_question_id_version_no"),
        ({"points": Decimal("0")}, "ck_question_version_points_positive"),
        ({"negative_marks": Decimal("-1")}, "ck_question_version_negative_marks_not_negative"),
        ({"msq_scoring": "SOMETIMES"}, "ck_question_version_msq_scoring"),
        ({"max_answer_length": 0}, "ck_question_version_max_answer_length_range"),
    ],
    ids=["duplicate-version-no", "zero-points", "negative-marks", "bad-scoring", "zero-length"],
)
async def test_version_constraints(
    factory: SessionFactory, world: tuple, values: dict[str, object], constraint: str
) -> None:
    college, question_id, _ = world
    async with tenant_session(factory, college.id) as s:
        question = await s.get(Question, question_id)
        assert question is not None
        fields: dict[str, object] = {"version_no": 2, "points": Decimal("1"), **values}
        s.add(
            QuestionVersion(
                question_id=question_id, body="b", created_by=question.owner_id, **fields
            )
        )
        with pytest.raises(IntegrityError, match=constraint):
            await s.flush()


async def test_question_type_and_visibility_are_checked(
    factory: SessionFactory, world: tuple
) -> None:
    college, question_id, _ = world
    for values, constraint in (
        ({"type": "ESSAY"}, "ck_question_type"),
        ({"visibility": "PUBLIC"}, "ck_question_visibility"),
    ):
        async with tenant_session(factory, college.id) as s:
            with pytest.raises(IntegrityError, match=constraint):
                await s.execute(update(Question).where(Question.id == question_id).values(**values))
