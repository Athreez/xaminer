"""SIGNAL_LOST: heartbeats arrive, but proctoring has stopped (PRD § 6.5, PRC-14; TCK-1105).

Each heartbeat of a proctored attempt says how many camera frames the exam screen has analysed.
When that number hasn't moved for 60 s while heartbeats keep coming, the server records (and
then keeps extending) one SIGNAL_LOST event. A lost connection never creates one: without
heartbeats nothing is checked, and on return the count has moved on (or the state has expired).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import ExamAttempt
from app.exams.models import ExamVersion
from app.proctoring.models import ProctoringEvent

STOPPED_AFTER = timedelta(seconds=60)
STATE_SECONDS = 300  # forgotten when heartbeats stop this long (e.g. a lost connection)


def _state_key(attempt_id: uuid.UUID) -> str:
    return f"attempt:{attempt_id}:proctoring"


def _mode_key(attempt_id: uuid.UUID) -> str:
    return f"attempt:{attempt_id}:proctored"


async def _proctored(session: AsyncSession, redis: Redis, attempt: ExamAttempt) -> bool:
    cached = await redis.get(_mode_key(attempt.id))
    if cached is not None:
        return bool(cached == b"1")
    mode = None
    if attempt.exam_version_id is not None:
        mode = await session.scalar(
            select(ExamVersion.snapshot["settings"]["proctoring_mode"].astext).where(
                ExamVersion.id == attempt.exam_version_id
            )
        )
    proctored = mode not in (None, "OFF")
    await redis.set(_mode_key(attempt.id), "1" if proctored else "0", ex=24 * 3600)
    return proctored


async def check(
    session: AsyncSession,
    redis: Redis,
    attempt: ExamAttempt,
    frames: int | None,
    now: datetime | None = None,
) -> None:
    """Called on every heartbeat of an attempt in progress."""
    if not await _proctored(session, redis, attempt):
        return
    now = now or datetime.now(UTC)
    key = _state_key(attempt.id)
    raw = await redis.get(key)
    state = json.loads(raw) if raw else None
    if state is None or (frames is not None and frames != state["frames"]):
        await redis.set(
            key, json.dumps({"frames": frames, "since": now.isoformat()}), ex=STATE_SECONDS
        )
        return
    await redis.expire(key, STATE_SECONDS)
    since = datetime.fromisoformat(state["since"])
    stopped = now - since
    if stopped < STOPPED_AFTER:
        return
    from app.proctoring.events import refresh_outcome, severity

    duration_ms = int(stopped.total_seconds() * 1000)
    level = severity("SIGNAL_LOST", duration_ms, {})
    statement = insert(ProctoringEvent).values(
        id=uuid.uuid4(),
        institution_id=attempt.institution_id,
        attempt_id=attempt.id,
        # One event per stop: the same id each heartbeat, so it's extended, not repeated.
        client_id=uuid.uuid5(attempt.id, f"signal-lost:{state['since']}"),
        kind="SIGNAL_LOST",
        occurred_at=since,
        duration_ms=duration_ms,
        details={},
        severity=level,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["attempt_id", "client_id"],
            set_={"duration_ms": duration_ms, "severity": level},
        )
    )
    await refresh_outcome(session, attempt.id)
    await session.commit()
