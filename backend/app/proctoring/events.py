"""Proctoring events: upload from the exam screen, the server's severity rules, the teacher's
review and the attempt's integrity outcome (PRD PRC-06, PRC-07, PRC-09..11; TCK-1101, TCK-1104,
TCK-1105, TCK-1106).

Severity comes from these rules, never from the browser:

| Event | LOW | MEDIUM | HIGH |
|---|---|---|---|
| TAB_SWITCH (left the exam page or window) | under 5 s | under 30 s | 30 s or more |
| FULLSCREEN_EXIT | back within 5 s | | longer |
| PASTE_BLOCKED (from outside the exam) | | under 200 characters | 200 or more |
| MULTIPLE_SCREENS | | always | |
| FACE_ABSENT (no face) | under 15 s | under 60 s | 60 s or more |
| MULTIPLE_FACES | | under 5 s | 5 s or more |
| GAZE_AWAY (head turned) | up to 30 s | longer | |
| VOICE_DETECTED (talking) | under 20 s | 20 s or more | |
| SCREEN_SHARE_STOPPED | under 10 s | under 60 s | 60 s or more |
| SIGNAL_LOST (from heartbeats) | | under 5 min | 5 min or more |

Camera events carry no pictures yet; until they do, these rules alone set their severity.

Events are accepted while the attempt is in progress and for 15 minutes after it ends (the last
ones may still be on their way). Nothing about events is ever returned to a student; the upload
answers 204 only.

Integrity outcome (PRC-11): no events or all dismissed → NO_CONCERNS; any flagged →
CONCERNS_CONFIRMED; else (any not reviewed) → PENDING_REVIEW. It's kept on the result, next to
the score, and never changes the score.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import ExamAttempt
from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import get_owned, not_found
from app.core.errors import AppError
from app.exams.models import Exam
from app.proctoring.models import ProctoringEvent

AFTER_END = timedelta(minutes=15)
# What the exam screen may send (SIGNAL_LOST is the server's own).
Kind = Literal[
    "FULLSCREEN_EXIT",
    "TAB_SWITCH",
    "PASTE_BLOCKED",
    "MULTIPLE_SCREENS",
    "FACE_ABSENT",
    "MULTIPLE_FACES",
    "GAZE_AWAY",
    "VOICE_DETECTED",
    "SCREEN_SHARE_STOPPED",
]
DETAILS = ("length", "how", "screens", "faces", "direction")
# Checked by the server from their pictures before a teacher sees them (app/proctoring/verdicts.py).
CHECKED = ("FACE_ABSENT", "MULTIPLE_FACES")
READY = ProctoringEvent.status == "READY"


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: uuid.UUID
    kind: Kind
    occurred_at: datetime
    duration_ms: int | None = Field(default=None, ge=0, le=24 * 3600 * 1000)
    # Small facts only (e.g. pasted length, how the page was left); never what was pasted.
    details: dict[str, int | str | bool] = Field(default={}, max_length=8)


class EventsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[EventIn] = Field(min_length=1, max_length=50)


def severity(kind: str, duration_ms: int | None, details: dict[str, Any]) -> str:
    seconds = (duration_ms or 0) / 1000
    if kind == "TAB_SWITCH":
        return "LOW" if seconds < 5 else "MEDIUM" if seconds < 30 else "HIGH"
    if kind == "FULLSCREEN_EXIT":
        return "LOW" if seconds < 5 else "HIGH"
    if kind == "PASTE_BLOCKED":
        length = details.get("length", 0)
        return "HIGH" if isinstance(length, int) and length >= 200 else "MEDIUM"
    if kind == "FACE_ABSENT":
        return "LOW" if seconds < 15 else "MEDIUM" if seconds < 60 else "HIGH"
    if kind == "MULTIPLE_FACES":
        return "MEDIUM" if seconds < 5 else "HIGH"
    if kind == "GAZE_AWAY":
        return "LOW" if seconds <= 30 else "MEDIUM"
    if kind == "VOICE_DETECTED":
        return "LOW" if seconds < 20 else "MEDIUM"
    if kind == "SCREEN_SHARE_STOPPED":
        return "LOW" if seconds < 10 else "MEDIUM" if seconds < 60 else "HIGH"
    if kind == "SIGNAL_LOST":
        return "MEDIUM" if seconds < 300 else "HIGH"
    return "MEDIUM"  # MULTIPLE_SCREENS


async def upload(
    session: AsyncSession, principal: Principal, attempt_id: uuid.UUID, body: EventsIn
) -> None:
    attempt = await get_owned(
        session,
        ExamAttempt,
        attempt_id,
        principal,
        owned=lambda a: a.student_id == principal.user_id,
    )
    now = datetime.now(UTC)
    ended = attempt.submitted_at or attempt.deadline_at
    if attempt.status == "VOIDED" or (attempt.status != "IN_PROGRESS" and now > ended + AFTER_END):
        raise AppError("ATTEMPT_CLOSED", "This attempt no longer takes events.", status_code=409)
    for event in body.events:
        details = {k: v for k, v in event.details.items() if k in DETAILS}
        await session.execute(
            insert(ProctoringEvent)
            .values(
                id=uuid.uuid4(),
                institution_id=attempt.institution_id,
                attempt_id=attempt.id,
                client_id=event.client_id,
                kind=event.kind,
                # The device's clock can be wrong: never later than now, never before the start.
                occurred_at=min(max(event.occurred_at, attempt.started_at), now),
                duration_ms=event.duration_ms,
                details=details,
                severity=severity(event.kind, event.duration_ms, details),
                status="PROCESSING" if event.kind in CHECKED else "READY",
            )
            .on_conflict_do_nothing(index_elements=["attempt_id", "client_id"])
        )
    await refresh_outcome(session, attempt.id)
    await session.commit()


# ----------------------------------------------------------------------------- teacher


class EventView(BaseModel):
    id: uuid.UUID
    kind: str
    occurred_at: datetime
    duration_ms: int | None
    details: dict[str, Any]
    severity: str
    decision: str | None
    note: str | None


Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["DISMISSED", "FLAGGED"]
    note: Note | None = None


def view(e: ProctoringEvent) -> EventView:
    return EventView(
        id=e.id,
        kind=e.kind,
        occurred_at=e.occurred_at,
        duration_ms=e.duration_ms,
        details=e.details,
        severity=e.severity,
        decision=e.decision,
        note=e.note,
    )


async def of_attempt(session: AsyncSession, attempt_id: uuid.UUID) -> list[EventView]:
    rows = await session.scalars(
        select(ProctoringEvent)
        .where(ProctoringEvent.attempt_id == attempt_id, READY)
        .order_by(ProctoringEvent.occurred_at, ProctoringEvent.id)
    )
    return [view(e) for e in rows]


async def counts(session: AsyncSession, attempt_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Events per attempt that aren't dismissed (for the monitor)."""
    if not attempt_ids:
        return {}
    rows = await session.execute(
        select(ProctoringEvent.attempt_id, func.count())
        .where(
            ProctoringEvent.attempt_id.in_(attempt_ids),
            READY,
            ProctoringEvent.decision.is_distinct_from("DISMISSED"),
        )
        .group_by(ProctoringEvent.attempt_id)
    )
    return {a: n for a, n in rows.all()}


async def decide(
    session: AsyncSession, principal: Principal, event_id: uuid.UUID, body: DecisionIn
) -> EventView:
    found = (
        await session.execute(
            select(ProctoringEvent)
            .join(ExamAttempt, ExamAttempt.id == ProctoringEvent.attempt_id)
            .join(Exam, Exam.id == ExamAttempt.exam_id)
            .where(ProctoringEvent.id == event_id, Exam.owner_id == principal.user_id, READY)
            .with_for_update(of=ProctoringEvent)
        )
    ).scalar_one_or_none()
    if found is None or found.institution_id != principal.institution_id:
        raise not_found()
    old = found.decision
    found.decision, found.note = body.decision, body.note or None
    found.decided_by, found.decided_at = principal.user_id, datetime.now(UTC)
    record(
        session,
        "proctoring_event.reviewed",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="attempt",
        target_id=found.attempt_id,
        changes={"event": str(found.id), "decision": {"old": old, "new": body.decision}},
    )
    await refresh_outcome(session, found.attempt_id)
    await session.commit()
    return view(found)


async def outcome(session: AsyncSession, attempt_id: uuid.UUID) -> str:
    decisions = list(
        await session.scalars(
            select(ProctoringEvent.decision).where(ProctoringEvent.attempt_id == attempt_id, READY)
        )
    )
    if "FLAGGED" in decisions:
        return "CONCERNS_CONFIRMED"
    if any(d is None for d in decisions):
        return "PENDING_REVIEW"
    return "NO_CONCERNS"


async def refresh_outcome(session: AsyncSession, attempt_id: uuid.UUID) -> None:
    """Keep the result's integrity outcome current (when there's a result yet)."""
    from app.results.models import Result

    await session.flush()
    result = await session.get(Result, attempt_id)
    if result is not None:
        result.integrity_outcome = await outcome(session, attempt_id)
