"""The only door to test cases (PRD CQ-05, NFR-02; SECURITY_AND_ACCESS.md § 3).

Hidden test cases are never shown or sent to a student: not their input, output or timings. To
keep that true by construction, every read of test cases goes through this module:

- `public_examples`: the public cases, which students see as examples. Student views use this.
- `all_test_cases`: hidden ones included. Only for the teacher's editor, the test bundle builder and
  validation. Never for anything a student receives.

`tests/test_hidden_cases.py` fails the build if any other module touches the `TestCase` table or
calls `all_test_cases`, so a new reader has to be added on purpose.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.questions.models import TestCase


async def public_examples(session: AsyncSession, version_id: uuid.UUID) -> list[TestCase]:
    """The public test cases of a version, in order: what students see as examples."""
    rows = await session.scalars(
        select(TestCase)
        .where(TestCase.version_id == version_id, TestCase.visibility == "PUBLIC")
        .order_by(TestCase.order_index)
    )
    return list(rows)


async def all_test_cases(session: AsyncSession, version_id: uuid.UUID) -> list[TestCase]:
    """Every test case of a version, hidden ones included, in order. Teacher and grading only."""
    rows = await session.scalars(
        select(TestCase).where(TestCase.version_id == version_id).order_by(TestCase.order_index)
    )
    return list(rows)
