"""Proctoring pictures (PRD PRC-05, PRC-10, PRC-13, PRC-17; TCK-1006, TCK-1102, TCK-1107).

The exam screen uploads, with the attempt token (never the access token):
- up to 3 camera pictures per event (start, middle, latest), for at most 30 events per attempt;
- a random camera picture every 20-40 s (spot check);
- pictures of the shared screen every 20-40 s and when the student leaves the exam page.

Each is checked (JPEG, PNG or WebP by its content, at most 1 MB), re-encoded (EXIF and anything
hidden dropped) and stored privately. The answer is always 204 and says nothing; uploads over
the limits are dropped quietly. They're accepted while the attempt is in progress and for 30
minutes after it ends (the last ones may still be on their way).

Spot checks are for the server's own check (phones, books: app/proctoring/verdicts.py): one that
finds nothing is deleted at once; any left unchecked are deleted after 30 minutes. Event and screen pictures are evidence: the
exam's teacher sees them through 5-minute links (each viewing is audit-logged), and they're
deleted `evidence_retention_days` after the exam closes.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import ExamAttempt
from app.audit.service import record
from app.auth.tokens import AttemptGrant, Principal
from app.authz.ownership import not_found
from app.core.errors import AppError
from app.core.ids import uuid7
from app.core.rate_limit import hit, rate_limited
from app.core.storage import EVIDENCE, Storage
from app.db.session import SessionFactory, system_session
from app.exams.models import Exam
from app.images.service import reencode
from app.platform.models import Institution
from app.proctoring.models import ProctoringCapture

AFTER_END = timedelta(minutes=30)
MAX_BYTES = 1024 * 1024
EVENTS_WITH_PICTURES = 30
PICTURES_PER_EVENT = 3
MAX_PER_ATTEMPT = 1000  # every kind together: ~3 hours of screen and camera pictures
PER_MINUTE = 30
SPOT_CHECK_KEPT = timedelta(minutes=30)  # normally deleted once checked; this if the check never ran
LINK_SECONDS = 300

Kind = Literal["CAMERA", "SCREEN"]
Purpose = Literal["EVENT", "SPOT_CHECK", "PERIODIC", "LEFT_PAGE"]


def _refuse(message: str) -> AppError:
    return AppError(
        "INVALID_PICTURE",
        message,
        status_code=422,
        details=[{"field": "image", "message": message, "type": "picture"}],
    )


async def upload(
    session: AsyncSession,
    redis: Redis,
    storage: Storage,
    grant: AttemptGrant,
    attempt_id: uuid.UUID,
    *,
    client_id: uuid.UUID,
    kind: Kind,
    purpose: Purpose,
    event_client_id: uuid.UUID | None,
    taken_at: datetime,
    data: bytes,
) -> None:
    if grant.attempt_id != attempt_id:
        raise not_found()
    attempt = await session.get(ExamAttempt, attempt_id)
    if attempt is None or attempt.student_id != grant.user_id:
        raise not_found()
    now = datetime.now(UTC)
    ended = attempt.submitted_at or attempt.deadline_at
    if attempt.status == "VOIDED" or (attempt.status != "IN_PROGRESS" and now > ended + AFTER_END):
        raise AppError("ATTEMPT_CLOSED", "This attempt no longer takes pictures.", status_code=409)
    if (purpose == "EVENT") != (event_client_id is not None):
        raise _refuse("Event pictures, and only they, name their event.")
    if kind == "SCREEN" and purpose not in ("PERIODIC", "LEFT_PAGE"):
        raise _refuse("Screen pictures are periodic or taken on leaving the page.")
    if kind == "CAMERA" and purpose not in ("EVENT", "SPOT_CHECK"):
        raise _refuse("Camera pictures belong to an event or a spot check.")
    if len(data) > MAX_BYTES:
        raise _refuse("The picture is larger than 1 MB.")
    limit = await hit(redis, f"captures:{attempt_id}", PER_MINUTE, 60)
    if not limit.allowed:
        raise rate_limited(limit.retry_after)
    if not await _room(session, attempt_id, purpose, event_client_id):
        return  # over a limit: dropped, and the answer doesn't say so
    clean, _, _ = reencode(data)
    capture_id = uuid7()
    key = f"{attempt.institution_id}/{attempt.id}/{capture_id}.webp"
    if purpose == "SPOT_CHECK":
        key = f"tmp/{key}"
    inserted = await session.scalar(
        insert(ProctoringCapture)
        .values(
            id=capture_id,
            institution_id=attempt.institution_id,
            attempt_id=attempt.id,
            client_id=client_id,
            kind=kind,
            purpose=purpose,
            event_client_id=event_client_id,
            # The device's clock can be wrong: never later than now, never before the start.
            taken_at=min(max(taken_at, attempt.started_at), now),
            storage_key=key,
            size=len(clean),
        )
        .on_conflict_do_nothing(index_elements=["attempt_id", "client_id"])
        .returning(ProctoringCapture.id)
    )
    if inserted is None:
        return  # sent before
    await storage.put(EVIDENCE, key, clean, "image/webp")
    await session.commit()


async def _room(
    session: AsyncSession, attempt_id: uuid.UUID, purpose: str, event_client_id: uuid.UUID | None
) -> bool:
    of_attempt = ProctoringCapture.attempt_id == attempt_id
    total = await session.scalar(select(func.count()).where(of_attempt))
    if (total or 0) >= MAX_PER_ATTEMPT:
        return False
    if purpose != "EVENT":
        return True
    same = await session.scalar(
        select(func.count()).where(of_attempt, ProctoringCapture.event_client_id == event_client_id)
    )
    if same:
        return same < PICTURES_PER_EVENT
    events = await session.scalar(
        select(func.count(ProctoringCapture.event_client_id.distinct())).where(of_attempt)
    )
    return (events or 0) < EVENTS_WITH_PICTURES


# ----------------------------------------------------------------------------- teacher


class Picture(BaseModel):
    kind: Kind
    purpose: Purpose
    taken_at: datetime
    url: str = Field(description="Works for 5 minutes")


class AttemptPictures(BaseModel):
    events: dict[uuid.UUID, list[Picture]] = Field(description="By event id, in time order")
    screen: list[Picture] = Field(description="Pictures of the shared screen, in time order")


async def for_teacher(
    session: AsyncSession,
    storage: Storage,
    principal: Principal,
    exam_id: uuid.UUID,
    attempt_id: uuid.UUID,
) -> AttemptPictures:
    """An attempt's event and screen pictures, for the exam's teacher (audit-logged)."""
    from app.proctoring.models import ProctoringEvent

    found = await session.scalar(
        select(ExamAttempt.id)
        .join(Exam, Exam.id == ExamAttempt.exam_id)
        .where(
            ExamAttempt.id == attempt_id,
            Exam.id == exam_id,
            Exam.owner_id == principal.user_id,
        )
    )
    if found is None:
        raise not_found()
    rows = await session.scalars(
        select(ProctoringCapture)
        .where(
            ProctoringCapture.attempt_id == attempt_id,
            ProctoringCapture.purpose != "SPOT_CHECK",
            ProctoringCapture.deleted_at.is_(None),
        )
        .order_by(ProctoringCapture.taken_at, ProctoringCapture.id)
    )
    event_ids = dict(
        (
            await session.execute(
                select(ProctoringEvent.client_id, ProctoringEvent.id).where(
                    ProctoringEvent.attempt_id == attempt_id, ProctoringEvent.status == "READY"
                )
            )
        )
        .tuples()
        .all()
    )
    pictures = AttemptPictures(events={}, screen=[])
    for c in rows:
        picture = Picture(
            kind=c.kind,  # type: ignore[arg-type]
            purpose=c.purpose,  # type: ignore[arg-type]
            taken_at=c.taken_at,
            url=storage.signed_url(EVIDENCE, c.storage_key, LINK_SECONDS),
        )
        if c.kind == "SCREEN":
            pictures.screen.append(picture)
        elif c.event_client_id in event_ids:
            pictures.events.setdefault(event_ids[c.event_client_id], []).append(picture)
    record(
        session,
        "proctoring.evidence_viewed",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="attempt",
        target_id=attempt_id,
        changes={"pictures": sum(map(len, pictures.events.values())) + len(pictures.screen)},
    )
    await session.commit()
    return pictures


# ----------------------------------------------------------------------------- cleanup


async def clean_up(factory: SessionFactory, storage: Storage, now: datetime | None = None) -> int:
    """Delete spot checks older than 10 minutes, and pictures whose exam closed more than its
    institution's retention ago. Rows stay, marked deleted. Returns how many were deleted."""
    now = now or datetime.now(UTC)
    deleted = 0
    async with system_session(factory) as session:
        retention = func.make_interval(0, 0, 0, Institution.evidence_retention_days)
        due = (
            select(ProctoringCapture.id, ProctoringCapture.storage_key)
            .join(ExamAttempt, ExamAttempt.id == ProctoringCapture.attempt_id)
            .join(Exam, Exam.id == ExamAttempt.exam_id)
            .join(Institution, Institution.id == ProctoringCapture.institution_id)
            .where(
                ProctoringCapture.deleted_at.is_(None),
                (
                    (ProctoringCapture.purpose == "SPOT_CHECK")
                    & (ProctoringCapture.created_at < now - SPOT_CHECK_KEPT)
                )
                | (Exam.close_at + retention < now),
            )
            .limit(1000)
        )
        while batch := (await session.execute(due)).tuples().all():
            await storage.delete(EVIDENCE, [key for _, key in batch])
            await session.execute(
                update(ProctoringCapture)
                .where(ProctoringCapture.id.in_([i for i, _ in batch]))
                .values(deleted_at=now)
            )
            await session.commit()
            deleted += len(batch)
    return deleted


async def overdue(session: AsyncSession, institution_id: uuid.UUID) -> int:
    """Pictures past retention not yet deleted (should be 0; shown on the admin settings)."""
    retention = func.make_interval(0, 0, 0, Institution.evidence_retention_days)
    count = await session.scalar(
        select(func.count())
        .select_from(ProctoringCapture)
        .join(ExamAttempt, ExamAttempt.id == ProctoringCapture.attempt_id)
        .join(Exam, Exam.id == ExamAttempt.exam_id)
        .join(Institution, Institution.id == ProctoringCapture.institution_id)
        .where(
            ProctoringCapture.institution_id == institution_id,
            ProctoringCapture.deleted_at.is_(None),
            Exam.close_at + retention + timedelta(hours=2) < func.now(),
        )
    )
    return count or 0
