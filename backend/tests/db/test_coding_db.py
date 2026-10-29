"""Coding question tables: config, test cases, reference solutions (PRD CQ-01..09, TCK-0701).

Runs as the app's own database user: the limits and the lock on published versions hold even if
application code tried to break them.
"""

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import SessionFactory, create_session_factory, tenant_session
from app.platform.models import Institution
from app.questions.models import (
    CodingConfig,
    Question,
    QuestionVersion,
    ReferenceSolution,
    TestCase,
)
from app.users.models import User
from cli import commands
from tests.db.question_helpers import purge_institutions

World = tuple[Institution, uuid.UUID]


@pytest.fixture
def factory(app_engine: AsyncEngine) -> SessionFactory:
    return create_session_factory(app_engine)


@pytest.fixture
async def world(factory: SessionFactory, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    college = await commands.create_institution(factory, f"Coding DB test {uuid.uuid4().hex[:8]}")
    async with tenant_session(factory, college.id) as s:
        teacher = User(email=f"t{uuid.uuid4().hex[:8]}@abc.edu", full_name="T", role="TEACHER")
        s.add(teacher)
        await s.flush()
        question = Question(owner_id=teacher.id, type="CODING")
        s.add(question)
        await s.flush()
        version = QuestionVersion(
            question_id=question.id,
            version_no=1,
            body="Print the sum of two numbers.",
            points=Decimal("10"),
            created_by=teacher.id,
        )
        s.add(version)
        await s.flush()
        s.add(
            CodingConfig(
                version_id=version.id,
                input_format="Two integers a and b",
                allowed_languages=[{"language_key": "python312", "starter_code": "a, b = ..."}],
            )
        )
        s.add_all(
            [
                TestCase(
                    version_id=version.id,
                    visibility="PUBLIC",
                    input="1 2",
                    expected_output="3",
                    order_index=0,
                ),
                TestCase(
                    version_id=version.id,
                    weight=3,
                    input="5 7",
                    expected_output="12",
                    order_index=1,
                ),
            ]
        )
        s.add(
            ReferenceSolution(
                version_id=version.id,
                language_key="python312",
                source="print(sum(map(int, input().split())))",
            )
        )
        question.current_version_id = version.id
        await s.commit()
    yield college, version.id
    await purge_institutions(migrator_engine, [college.id])


async def refused(factory: SessionFactory, college: Institution, statement) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session(factory, college.id) as s:
        with pytest.raises(DBAPIError) as caught:
            await s.execute(statement)
            await s.flush()
        await s.rollback()
    return str(caught.value)


async def test_defaults_follow_the_prd(factory: SessionFactory, world: World) -> None:
    college, version_id = world
    async with tenant_session(factory, college.id) as s:
        config = await s.get_one(CodingConfig, version_id)
        cases = (await s.scalars(select(TestCase).order_by(TestCase.order_index))).all()
    assert (config.comparison_mode, config.time_limit_ms, config.memory_limit_mb) == (
        "TRIM",
        2000,
        256,
    )
    assert config.partial_scoring and config.run_code_allowed and config.max_submissions == 10
    assert config.validation_status == "NEEDS_VALIDATION" and config.validation_report is None
    assert [(c.visibility, c.weight) for c in cases] == [("PUBLIC", 1), ("HIDDEN", 3)]


async def test_limits_are_enforced(factory: SessionFactory, world: World) -> None:
    college, version_id = world
    config = CodingConfig.version_id == version_id
    cases = TestCase.version_id == version_id
    bad = [
        update(CodingConfig).where(config).values(time_limit_ms=50),
        update(CodingConfig).where(config).values(time_limit_ms=10_001),
        update(CodingConfig).where(config).values(memory_limit_mb=1024),
        update(CodingConfig).where(config).values(comparison_mode="FUZZY"),
        update(CodingConfig).where(config).values(validation_status="MAYBE"),
        update(CodingConfig).where(config).values(max_submissions=0),
        update(CodingConfig).where(config).values(allowed_languages={"python312": ""}),
        update(TestCase).where(cases).values(visibility="SECRET"),
        update(TestCase).where(cases).values(weight=0),
        update(TestCase).where(cases).values(input="x" * 1_048_577),  # over 1 MB
        update(ReferenceSolution)
        .where(ReferenceSolution.version_id == version_id)
        .values(language_key="cobol"),
    ]
    for statement in bad:
        await refused(factory, college, statement)

    async with tenant_session(factory, college.id) as s:  # one reference per language
        s.add(ReferenceSolution(version_id=version_id, language_key="python312", source="pass"))
        with pytest.raises(IntegrityError):
            await s.flush()


async def test_test_cases_can_swap_places(factory: SessionFactory, world: World) -> None:
    college, _ = world
    async with tenant_session(factory, college.id) as s:
        first, second = (await s.scalars(select(TestCase).order_by(TestCase.order_index))).all()
        first.order_index, second.order_index = 1, 0  # checked at commit, not row by row
        await s.commit()
    async with tenant_session(factory, college.id) as s:
        inputs = (await s.scalars(select(TestCase.input).order_by(TestCase.order_index))).all()
    assert inputs == ["5 7", "1 2"]


async def test_locked_version_freezes_its_coding_setup(
    factory: SessionFactory, world: World
) -> None:
    college, version_id = world
    async with tenant_session(factory, college.id) as s:
        await s.execute(
            update(QuestionVersion).where(QuestionVersion.id == version_id).values(is_locked=True)
        )
        await s.commit()

    attempts = [
        update(CodingConfig)
        .where(CodingConfig.version_id == version_id)
        .values(time_limit_ms=3000),
        update(TestCase).where(TestCase.version_id == version_id).values(expected_output="13"),
        delete(TestCase).where(TestCase.version_id == version_id),
        update(ReferenceSolution)
        .where(ReferenceSolution.version_id == version_id)
        .values(source="x"),
        delete(ReferenceSolution).where(ReferenceSolution.version_id == version_id),
    ]
    for statement in attempts:
        assert "is locked" in await refused(factory, college, statement), statement

    async with tenant_session(factory, college.id) as s:  # nor can a test case be added
        s.add(TestCase(version_id=version_id, input="0 0", expected_output="0", order_index=5))
        with pytest.raises(DBAPIError, match="is locked"):
            await s.flush()


async def test_deleting_a_draft_version_removes_its_coding_setup(
    factory: SessionFactory, world: World
) -> None:
    college, version_id = world
    async with tenant_session(factory, college.id) as s:
        await s.execute(update(Question).values(current_version_id=None))
        await s.execute(delete(QuestionVersion).where(QuestionVersion.id == version_id))
        await s.commit()
        left = [
            await s.scalar(select(func.count()).select_from(model))
            for model in (CodingConfig, TestCase, ReferenceSolution)
        ]
    assert left == [0, 0, 0]
