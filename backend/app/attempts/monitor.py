"""The live exam monitor (PRD MON-01, MON-06; TCK-1201).

One row per assigned student: not started, in progress, submitted or voided; questions answered
of the total; time left; connection; answers still waiting on their device; proctoring events.
The exam screen sends a heartbeat every 15 s into Redis (`heartbeat.py`), so connection and
waiting answers come from there in one round trip; everything else is a handful of grouped
queries, whatever the number of students.

Connection: online when the last heartbeat is under 40 s old (two missed beats are tolerated),
weak under 2 min, else offline. A gap is never a proctoring event (architecture § 9.6).

Live alerts (proctored exams): each row says what proctoring sees right now (from the latest
heartbeat: no face for 40 s, another person...), and `alerts` lists the exam's medium and high
events of the last 30 minutes, newest first. Only the teacher sees either.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import distinct, func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.heartbeat import Happening, live_key
from app.attempts.models import Answer, AttemptQuestion, ExamAttempt
from app.auth.tokens import Principal
from app.authz.ownership import get_owned
from app.exams.models import Exam, ExamAssignment
from app.execution.models import CodingSubmission
from app.proctoring.events import counts as event_counts
from app.proctoring.models import ProctoringEvent
from app.users.models import User
from domain_core import timer

ONLINE_SECONDS = 40
WEAK_SECONDS = 120
ALERT_MINUTES = 30
MAX_ALERTS = 20

Status = Literal["NOT_STARTED", "IN_PROGRESS", "SUBMITTED", "AUTO_SUBMITTED", "VOIDED"]
Connection = Literal["ONLINE", "WEAK", "OFFLINE"]


class MonitorRow(BaseModel):
    student_id: uuid.UUID
    full_name: str
    email: str
    roll_no: str | None
    attempt_id: uuid.UUID | None
    status: Status
    answered: int
    total: int
    seconds_left: int | None = Field(description="In progress only")
    extra_minutes: int
    connection: Connection | None = Field(description="In progress only")
    last_seen_at: datetime | None
    unsynced: int = Field(description="Answers waiting on the student's device")
    event_count: int = Field(description="Proctoring events (with proctoring)")
    happening: list[Happening] = Field(
        default=[], description="What proctoring sees right now (online students only)"
    )


class Alert(BaseModel):
    event_id: uuid.UUID
    attempt_id: uuid.UUID
    full_name: str
    kind: str
    severity: str
    occurred_at: datetime
    duration_ms: int | None


class MonitorView(BaseModel):
    server_time: datetime
    rows: list[MonitorRow]
    alerts: list[Alert] = Field(description="Medium and high events of the last 30 minutes")
    counts: dict[str, int] = Field(description="Students per status")


def connection_of(last_seen: datetime | None, now: datetime) -> Connection:
    if last_seen is None:
        return "OFFLINE"
    age = (now - last_seen).total_seconds()
    return "ONLINE" if age < ONLINE_SECONDS else "WEAK" if age < WEAK_SECONDS else "OFFLINE"


async def monitor(
    session: AsyncSession, redis: Redis, principal: Principal, exam_id: uuid.UUID
) -> MonitorView:
    exam = await get_owned(
        session, Exam, exam_id, principal, owned=lambda e: e.owner_id == principal.user_id
    )
    now = datetime.now(UTC)
    students = (
        await session.execute(
            select(User)
            .join(ExamAssignment, ExamAssignment.student_id == User.id)
            .where(ExamAssignment.exam_id == exam.id)
            .order_by(User.full_name, User.id)
        )
    ).scalars()
    # The latest attempt per student (a voided one is kept only if nothing replaced it).
    attempts: dict[uuid.UUID, ExamAttempt] = {}
    for found in await session.scalars(
        select(ExamAttempt)
        .where(ExamAttempt.exam_id == exam.id, ExamAttempt.is_preview.is_(False))
        .order_by(ExamAttempt.started_at)
    ):
        attempts[found.student_id] = found
    ids = [a.id for a in attempts.values()]

    totals = dict(
        (
            await session.execute(
                select(AttemptQuestion.attempt_id, func.count())
                .where(AttemptQuestion.attempt_id.in_(ids))
                .group_by(AttemptQuestion.attempt_id)
            )
        )
        .tuples()
        .all()
    )
    written = select(Answer.attempt_id, Answer.exam_question_id).where(
        Answer.attempt_id.in_(ids),
        (func.cardinality(Answer.selected_option_ids) > 0)
        | (func.length(func.trim(func.coalesce(Answer.text_answer, ""))) > 0),
    )
    coded = select(CodingSubmission.attempt_id, CodingSubmission.exam_question_id).where(
        CodingSubmission.attempt_id.in_(ids)
    )
    done = union(written, coded).subquery()
    answered: dict[uuid.UUID, int] = dict(
        (
            await session.execute(
                select(done.c.attempt_id, func.count(distinct(done.c.exam_question_id))).group_by(
                    done.c.attempt_id
                )
            )
        )
        .tuples()
        .all()
    )

    events = await event_counts(session, ids)
    live_ids = [a.id for a in attempts.values() if a.status == "IN_PROGRESS"]
    beats = await redis.mget([live_key(i) for i in live_ids]) if live_ids else []
    live = {i: json.loads(b) for i, b in zip(live_ids, beats, strict=True) if b}

    rows: list[MonitorRow] = []
    for user in students:
        a = attempts.get(user.id)
        beat = live.get(a.id) if a else None
        last_seen = (
            datetime.fromisoformat(beat["at"]) if beat else (a.last_heartbeat_at if a else None)
        )
        in_progress = a is not None and a.status == "IN_PROGRESS"
        rows.append(
            MonitorRow(
                student_id=user.id,
                full_name=user.full_name,
                email=user.email,
                roll_no=user.roll_no,
                attempt_id=a.id if a else None,
                status=a.status if a else "NOT_STARTED",  # type: ignore[arg-type]
                answered=answered.get(a.id, 0) if a else 0,
                total=totals.get(a.id, 0) if a else 0,
                seconds_left=timer.seconds_left(a.deadline_at, now) if in_progress and a else None,
                extra_minutes=a.extra_minutes if a else 0,
                connection=connection_of(last_seen, now) if in_progress else None,
                last_seen_at=last_seen,
                unsynced=int(beat.get("unsynced", 0)) if beat else 0,
                event_count=events.get(a.id, 0) if a else 0,  # not dismissed
                happening=[Happening.model_validate(h) for h in beat.get("now", [])]
                if beat and connection_of(last_seen, now) == "ONLINE"
                else [],
            )
        )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    names = {a.id: a.student_id for a in attempts.values()}
    people = {row.student_id: row.full_name for row in rows}
    recent = await session.scalars(
        select(ProctoringEvent)
        .where(
            ProctoringEvent.attempt_id.in_(ids),
            ProctoringEvent.status == "READY",
            ProctoringEvent.severity.in_(("MEDIUM", "HIGH")),
            ProctoringEvent.decision.is_(None),
            ProctoringEvent.created_at > now - timedelta(minutes=ALERT_MINUTES),
        )
        .order_by(ProctoringEvent.created_at.desc())
        .limit(MAX_ALERTS)
    )
    alerts = [
        Alert(
            event_id=e.id,
            attempt_id=e.attempt_id,
            full_name=people.get(names[e.attempt_id], ""),
            kind=e.kind,
            severity=e.severity,
            occurred_at=e.occurred_at,
            duration_ms=e.duration_ms,
        )
        for e in recent
    ]
    return MonitorView(server_time=now, rows=rows, counts=counts, alerts=alerts)
