"""Consent before a proctored exam (PRD PRC-03; SECURITY § 8.1, § 8.2; TCK-1001).

The student answers the consent text frozen into the published exam; each answer is a new row
with that text's hash, so it's always known which wording was agreed to. Starting a proctored
exam needs the latest answer to the current wording to be "accepted" (checked in
`attempts.attempt.start`). The camera isn't turned on before then (the device check page).
"""

import hashlib
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import not_found
from app.core.errors import AppError
from app.exams.models import Exam, ExamAssignment, ExamVersion
from app.exams.schemas import ProctoringMode
from app.proctoring.models import ConsentRecord

Decision = Literal["ACCEPTED", "DECLINED"]


class ConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision


class ConsentView(BaseModel):
    proctoring_mode: ProctoringMode
    screen_sharing: bool = Field(description="The whole screen must be shared during the exam")
    text: str = Field(description="Markdown, the wording the student answers")
    decision: Decision | None = Field(description="Your latest answer to this wording, if any")
    decided_at: datetime | None


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def mode(snapshot: dict[str, Any]) -> str:
    return str(snapshot["settings"].get("proctoring_mode") or "OFF")


def screen_sharing(snapshot: dict[str, Any]) -> bool:
    """Proctored exams share the whole screen unless the teacher turned it off (published before
    the setting existed: on)."""
    settings = snapshot["settings"]
    detectors = settings.get("proctoring_detectors") or {}
    return mode(snapshot) != "OFF" and bool(detectors.get("screen", True))


async def latest(
    session: AsyncSession, exam_id: uuid.UUID, student_id: uuid.UUID, text: str
) -> ConsentRecord | None:
    """The student's latest answer to this exact wording."""
    return await session.scalar(
        select(ConsentRecord)
        .where(
            ConsentRecord.exam_id == exam_id,
            ConsentRecord.student_id == student_id,
            ConsentRecord.consent_text_hash == text_hash(text),
        )
        .order_by(ConsentRecord.decided_at.desc(), ConsentRecord.id.desc())
        .limit(1)
    )


async def accepted(
    session: AsyncSession, exam_id: uuid.UUID, student_id: uuid.UUID, snapshot: dict[str, Any]
) -> bool:
    """True when the exam isn't proctored, or the student accepted its current wording."""
    if mode(snapshot) == "OFF":
        return True
    found = await latest(session, exam_id, student_id, snapshot.get("consent_text") or "")
    return found is not None and found.decision == "ACCEPTED"


async def _proctored_exam(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID
) -> tuple[Exam, dict[str, Any]]:
    """A published exam the student is assigned to (else 404), with its frozen copy; refused
    when it isn't proctored."""
    row = (
        await session.execute(
            select(Exam, ExamVersion.snapshot)
            .join(ExamAssignment, ExamAssignment.exam_id == Exam.id)
            .join(ExamVersion, ExamVersion.id == Exam.published_version_id)
            .where(
                Exam.id == exam_id,
                ExamAssignment.student_id == principal.user_id,
                Exam.status == "PUBLISHED",
            )
        )
    ).first()
    if row is None:
        raise not_found()
    exam, snapshot = row[0], row[1]
    if mode(snapshot) == "OFF":
        raise AppError("NOT_PROCTORED", "This exam isn't proctored.", status_code=409)
    return exam, snapshot


def _view(snapshot: dict[str, Any], found: ConsentRecord | None) -> ConsentView:
    return ConsentView(
        proctoring_mode=mode(snapshot),  # type: ignore[arg-type]
        screen_sharing=screen_sharing(snapshot),
        text=snapshot.get("consent_text") or "",
        decision=found.decision if found else None,  # type: ignore[arg-type]
        decided_at=found.decided_at if found else None,
    )


async def get(session: AsyncSession, principal: Principal, exam_id: uuid.UUID) -> ConsentView:
    exam, snapshot = await _proctored_exam(session, principal, exam_id)
    found = await latest(session, exam.id, principal.user_id, snapshot.get("consent_text") or "")
    return _view(snapshot, found)


async def decide(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID, body: ConsentIn
) -> ConsentView:
    exam, snapshot = await _proctored_exam(session, principal, exam_id)
    text = snapshot.get("consent_text") or ""
    row = ConsentRecord(
        institution_id=principal.institution_id,
        exam_id=exam.id,
        student_id=principal.user_id,
        consent_text_hash=text_hash(text),
        decision=body.decision,
    )
    session.add(row)
    await session.flush()
    record(
        session,
        "proctoring.consent_recorded"
        if body.decision == "ACCEPTED"
        else "proctoring.consent_declined",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="exam",
        target_id=exam.id,
        changes={"consent_text_hash": row.consent_text_hash},
    )
    await session.commit()
    await session.refresh(row)
    return _view(snapshot, row)
