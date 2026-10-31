"""The exam screen's heartbeat (PRD ATT-04, ATT-12; architecture § 9).

Sent every few seconds. It answers with what the screen must react to: the attempt's status and
deadline (a teacher may have extended, force-submitted or voided it) and the server's clock. It
also renews the attempt token used for proctoring uploads, and tells whether proctoring is still
running (`proctoring.signal`).

Heartbeats land in Redis (the live monitor reads them there). Postgres gets `last_heartbeat_at`
at most once a minute per attempt, so a full exam hall doesn't turn into a stream of writes.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import ExamAttempt
from app.attempts.submit import finalize_if_overdue
from app.auth.tokens import AttemptGrant, Principal, create_attempt_token
from app.authz.ownership import get_owned
from app.proctoring import signal
from domain_core import timer

LIVE_SECONDS = 300  # how long the monitor keeps showing the last heartbeat
DB_EVERY_SECONDS = 60  # at most one Postgres write per attempt in this time
TOKEN_MINUTES = 10


def live_key(attempt_id: uuid.UUID) -> str:
    return f"attempt:{attempt_id}:heartbeat"


def _db_gate_key(attempt_id: uuid.UUID) -> str:
    return f"attempt:{attempt_id}:heartbeat-written"


NowKind = Literal[
    "FACE_ABSENT",
    "MULTIPLE_FACES",
    "GAZE_AWAY",
    "VOICE_DETECTED",
    "SCREEN_SHARE_STOPPED",
    "CAMERA_OFF",
]


class Happening(BaseModel):
    """Something proctoring sees right now (for the teacher's live monitor, never the student)."""

    model_config = ConfigDict(extra="forbid")

    kind: NowKind
    seconds: int = Field(ge=0, le=24 * 3600, description="For how long so far")


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unsynced: int = Field(default=0, ge=0, le=10_000, description="Answers waiting on the device")
    proctoring_frames: int | None = Field(
        default=None,
        ge=0,
        le=100_000_000,
        description="Proctored exams: camera frames analysed so far on this page",
    )
    proctoring_now: list[Happening] = Field(
        default=[], max_length=6, description="Proctored exams: what's going on right now"
    )


class HeartbeatOut(BaseModel):
    status: Literal["IN_PROGRESS", "SUBMITTED", "AUTO_SUBMITTED", "VOIDED"]
    deadline_at: datetime = Field(description="May move later if a teacher extends the attempt")
    extra_minutes: int
    server_time: datetime
    seconds_left: int
    accepts_saves: bool = Field(description="False once the deadline and its grace have passed")
    attempt_token: str | None = Field(description="For proctoring uploads; only while in progress")
    attempt_token_expires_in: int | None = Field(description="Seconds")


async def beat(
    session: AsyncSession,
    redis: Redis,
    principal: Principal,
    attempt_id: uuid.UUID,
    body: HeartbeatIn,
    secret: str,
) -> HeartbeatOut:
    now = datetime.now(UTC)
    attempt = await get_owned(
        session,
        ExamAttempt,
        attempt_id,
        principal,
        owned=lambda a: a.student_id == principal.user_id,
    )
    # A voided or submitted attempt still answers, so the screen learns what the teacher did.
    await finalize_if_overdue(session, attempt, now)  # an overdue attempt ends here, if not already
    in_progress = attempt.status == "IN_PROGRESS"
    if in_progress:
        await redis.set(
            live_key(attempt.id),
            json.dumps(
                {
                    "at": now.isoformat(),
                    "unsynced": body.unsynced,
                    "now": [h.model_dump() for h in body.proctoring_now],
                }
            ),
            ex=LIVE_SECONDS,
        )
        if await redis.set(_db_gate_key(attempt.id), "1", nx=True, ex=DB_EVERY_SECONDS):
            await session.execute(
                update(ExamAttempt)
                .where(ExamAttempt.id == attempt.id)
                .values(last_heartbeat_at=now)
            )
            await session.commit()
        await signal.check(session, redis, attempt, body.proctoring_frames, now)
    token = (
        create_attempt_token(
            AttemptGrant(attempt.id, principal.user_id, principal.institution_id),
            secret,
            TOKEN_MINUTES,
            now,
        )
        if in_progress
        else None
    )
    return HeartbeatOut(
        status=attempt.status,  # type: ignore[arg-type]
        deadline_at=attempt.deadline_at,
        extra_minutes=attempt.extra_minutes,
        server_time=now,
        seconds_left=timer.seconds_left(attempt.deadline_at, now),
        accepts_saves=in_progress and timer.accepts_saves(attempt.deadline_at, now),
        attempt_token=token,
        attempt_token_expires_in=TOKEN_MINUTES * 60 if token else None,
    )
