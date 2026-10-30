"""Publishing an exam (PRD EX-05, EX-06; architecture D-11).

One transaction: refuse while the publish check finds anything blocking, pin each question to its
current version and lock that version, then write a frozen copy of the exam (settings, consent
text and every question as students will see it, with answers for grading) and its SHA-256.
After this only the window's end and the assignments can change; question edits make new versions
that this exam never sees.
"""

import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import get_owned
from app.core.errors import AppError
from app.exams import notify, publish_check
from app.exams.models import Exam, ExamAssignment, ExamQuestion, ExamVersion
from app.platform.consent import standard_consent
from app.platform.models import Institution
from app.questions import student_view
from app.questions.models import Question, QuestionOption, QuestionVersion

SNAPSHOT_FORMAT = 1


def _plain(value: Any) -> Any:
    """JSON-ready, the same way every time (so the hash is stable)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def content_hash(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def build_snapshot(
    session: AsyncSession, exam: Exam, *, publishing: bool
) -> tuple[dict[str, Any], int]:
    """The exam as students will see it, frozen: settings, consent text and every question with
    its options, answer keys and marks. Returns the snapshot and the number of questions.

    `publishing`: also pin each question to this version and lock the versions (no edits after),
    reading them under a lock. A teacher's preview builds the same snapshot without either.
    """
    rows = (
        await session.execute(
            select(ExamQuestion, Question)
            .join(Question, Question.id == ExamQuestion.question_id)
            .where(ExamQuestion.exam_id == exam.id)
            .order_by(ExamQuestion.order_index)
        )
    ).all()
    version_ids = [q.current_version_id for _, q in rows]
    query = select(QuestionVersion).where(QuestionVersion.id.in_(version_ids))
    if publishing:
        # Lock the versions while reading them, so an edit can't slip in between snapshot and lock.
        query = query.with_for_update()
    versions = {v.id: v for v in await session.scalars(query)}
    options: dict[uuid.UUID, list[QuestionOption]] = {vid: [] for vid in version_ids}  # type: ignore[misc]
    for option in await session.scalars(
        select(QuestionOption)
        .where(QuestionOption.version_id.in_(version_ids))
        .order_by(QuestionOption.order_index)
    ):
        options[option.version_id].append(option)

    questions = []
    total = Decimal(0)
    for eq, question in rows:
        v = versions[question.current_version_id]  # type: ignore[index]
        if publishing:
            eq.pinned_version_id = v.id
        points = eq.points if eq.points is not None else v.points
        total += points
        questions.append(
            {
                "exam_question_id": eq.id,
                "question_id": question.id,
                "version_id": v.id,
                "version_no": v.version_no,
                "type": question.type,
                "points": points,
                "negative_marks": eq.negative_marks
                if eq.negative_marks is not None
                else v.negative_marks,
                "body": v.body,
                "msq_scoring": v.msq_scoring,
                "max_answer_length": v.max_answer_length,
                "rubric": v.rubric,
                "options": [
                    {"id": o.id, "label": o.label, "is_correct": o.is_correct}
                    for o in options[v.id]
                ],
                # Student-safe only: hidden test cases stay in their table, for grading.
                "coding": await student_view.coding_part(session, v.id)
                if question.type == "CODING"
                else None,
            }
        )
    if publishing:
        await session.execute(
            update(QuestionVersion)
            .where(QuestionVersion.id.in_(version_ids), QuestionVersion.is_locked.is_(False))
            .values(is_locked=True)
        )

    consent = exam.consent_text
    if exam.proctoring_mode != "OFF" and not consent:
        # The institution's wording, else the standard text (SECURITY § 8.2).
        institution = await session.get_one(Institution, exam.institution_id)
        consent = institution.default_consent_text or standard_consent(
            exam.proctoring_mode,
            institution.evidence_retention_days,
            screen=bool((exam.proctoring_detectors or {}).get("screen", True)),
        )
    snapshot = _plain(
        {
            "format": SNAPSHOT_FORMAT,
            "exam_id": exam.id,
            "title": exam.title,
            "instructions": exam.instructions,
            "settings": {
                "open_at": exam.open_at,
                "close_at": exam.close_at,
                "duration_min": exam.duration_min,
                "navigation_mode": exam.navigation_mode,
                "shuffle_questions": exam.shuffle_questions,
                "shuffle_options": exam.shuffle_options,
                "run_code_enabled": exam.run_code_enabled,
                "browser_checks": exam.browser_checks,
                "release_policy": exam.release_policy,
                "counted_submission": exam.counted_submission,
                "pass_percent": exam.pass_percent,
                "proctoring_mode": exam.proctoring_mode,
                "proctoring_detectors": exam.proctoring_detectors,
            },
            "consent_text": consent,
            "total_points": total,
            "questions": questions,
        }
    )
    return snapshot, len(questions)


async def publish(session: AsyncSession, principal: Principal, exam_id: uuid.UUID) -> Exam:
    exam = await get_owned(
        session, Exam, exam_id, principal, owned=lambda e: e.owner_id == principal.user_id
    )
    # Lock the exam row: a second click (or tab) waits here, then sees it's no longer a draft.
    await session.execute(select(Exam.id).where(Exam.id == exam.id).with_for_update())
    await session.refresh(exam)

    result = await publish_check.check(session, exam)
    if not result.can_publish:
        raise AppError(
            "PUBLISH_BLOCKED",
            result.blocks[0].message
            if len(result.blocks) == 1
            else f"{len(result.blocks)} things need fixing before publishing.",
            status_code=409,
            details=[
                {
                    "field": b.field or "exam",
                    "message": b.message,
                    "type": b.code,
                    "question_id": str(b.question_id) if b.question_id else None,
                }
                for b in result.blocks
            ],
        )

    snapshot, question_count = await build_snapshot(session, exam, publishing=True)
    latest = await session.scalar(
        select(func.max(ExamVersion.version_no)).where(ExamVersion.exam_id == exam.id)
    )
    version = ExamVersion(
        exam_id=exam.id,
        version_no=(latest or 0) + 1,
        snapshot=snapshot,
        content_hash=content_hash(snapshot),
    )
    session.add(version)
    await session.flush()
    exam.status = "PUBLISHED"
    exam.published_version_id = version.id
    record(
        session,
        "exam.published",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="exam",
        target_id=exam.id,
        changes={
            "version_no": version.version_no,
            "content_hash": version.content_hash,
            "questions": question_count,
        },
    )
    students = await session.scalars(
        select(ExamAssignment.student_id).where(ExamAssignment.exam_id == exam.id)
    )
    await notify.exam_assigned(session, exam, list(students))
    await session.commit()
    return exam
