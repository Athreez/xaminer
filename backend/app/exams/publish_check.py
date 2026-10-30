"""What stops an exam being published, and what is only worth a warning (PRD § 6.4).

Every message names the thing to fix ("Question 3 'Explain recursion' …"), so the teacher can go
straight to it. Publishing (TCK-0506) runs the same check and refuses while anything blocks.
"""

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import Principal
from app.exams.models import Exam, ExamAssignment, ExamQuestion
from app.exams.service import get_own
from app.questions.models import CodingConfig, Question, QuestionVersion
from app.questions.service import title_of

SECONDS_PER_QUESTION = 60  # less than this on average is "very short"


class Issue(BaseModel):
    code: str
    message: str
    field: str | None = Field(description="The exam setting to fix, if it's a setting")
    question_id: uuid.UUID | None = Field(description="The question to fix, if it's a question")


class PublishCheck(BaseModel):
    can_publish: bool
    blocks: list[Issue] = Field(description="Must be fixed before publishing")
    warnings: list[Issue] = Field(description="Worth a look; publishing is still allowed")


async def check(session: AsyncSession, exam: Exam, now: datetime | None = None) -> PublishCheck:
    now = now or datetime.now(UTC)
    blocks: list[Issue] = []
    warnings: list[Issue] = []

    def block(
        code: str, message: str, field: str | None = None, question: uuid.UUID | None = None
    ) -> None:
        blocks.append(Issue(code=code, message=message, field=field, question_id=question))

    def warn(
        code: str, message: str, field: str | None = None, question: uuid.UUID | None = None
    ) -> None:
        warnings.append(Issue(code=code, message=message, field=field, question_id=question))

    if exam.status != "DRAFT":
        block("NOT_A_DRAFT", f"The exam is already {exam.status.lower()}.", "status")

    rows = (
        await session.execute(
            select(ExamQuestion, Question, QuestionVersion)
            .join(Question, Question.id == ExamQuestion.question_id)
            .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
            .where(ExamQuestion.exam_id == exam.id)
            .order_by(ExamQuestion.order_index)
        )
    ).all()
    if not rows:
        block("NO_QUESTIONS", "Add at least one question.", "questions")
    for position, (_, question, version) in enumerate(rows, start=1):
        name = f"Question {position} “{title_of(version.body, 50)}”"
        if (
            question.type == "CODING"
            and await session.scalar(
                select(CodingConfig.validation_status).where(CodingConfig.version_id == version.id)
            )
            != "PASSED"
        ):
            block(
                "CODING_NOT_VALIDATED",
                f"{name} hasn't passed validation yet.",
                question=question.id,
            )
        if question.type == "DESCRIPTIVE" and not version.rubric:
            warn("NO_RUBRIC", f"{name} has no rubric for graders.", question=question.id)
    # A question can't be worth 0 points (the database requires more), so that warning can't arise.

    if exam.open_at is None or exam.close_at is None:
        block(
            "NO_WINDOW",
            "Set when the exam opens and closes.",
            "open_at" if exam.open_at is None else "close_at",
        )
    elif exam.close_at <= now:
        block(
            "WINDOW_IN_PAST",
            "The exam window has already closed. Choose a later close time.",
            "close_at",
        )
    if exam.duration_min is None:
        block("NO_DURATION", "Set how many minutes students get.", "duration_min")
    elif exam.open_at and exam.close_at:
        window_min = (exam.close_at - exam.open_at).total_seconds() / 60
        if exam.duration_min > window_min:
            block(
                "DURATION_LONGER_THAN_WINDOW",
                f"The duration ({exam.duration_min} min) is longer than the window "
                f"({int(window_min)} min).",
                "duration_min",
            )
    if exam.duration_min and rows and exam.duration_min * 60 / len(rows) < SECONDS_PER_QUESTION:
        warn(
            "SHORT_DURATION",
            f"{exam.duration_min} min for {len(rows)} questions is less than a minute each.",
            "duration_min",
        )

    assigned = await session.scalar(select(func.count()).where(ExamAssignment.exam_id == exam.id))
    if not assigned:
        block("NO_STUDENTS", "Assign at least one student or group.", "assignments")

    if exam.shuffle_questions and exam.navigation_mode == "SEQUENTIAL":
        warn(
            "SHUFFLE_WITH_SEQUENTIAL",
            "Questions are shuffled and must be answered in order: students can't go back "
            "to earlier ones.",
            "shuffle_questions",
        )

    return PublishCheck(can_publish=not blocks, blocks=blocks, warnings=warnings)


async def check_own(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID
) -> PublishCheck:
    return await check(session, await get_own(session, principal, exam_id))
