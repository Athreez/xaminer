"""The server's check of proctoring pictures (PRD PRC-07, § 6.5; TCK-1103, TCK-1104).

`dispatch` (every 30 s) sends pictures to the inference-worker:
- camera events the server checks (no face, another person) once their pictures are in (3, or
  after 2 minutes, whichever is first); an event with no pictures at all is shown unchecked;
- each spot check once.

`apply` (app-worker, on each answer) decides, from what the models found:
- no face: confirmed by pictures with no face, rejected if every picture shows one;
- another person: confirmed by pictures with a second face (at least 20 % of the main one's
  size) or two people, rejected otherwise;
- a rejected event is never shown and its pictures are deleted; the share of pictures that
  confirm it is its confidence, and below 0.6 its severity drops one level;
- a spot check with a phone (score 0.5 or more) becomes PHONE_DETECTED (MEDIUM, HIGH from 0.85),
  else with a book (closed-book exams only) BOOK_DETECTED (LOW), its picture kept as evidence;
  a spot check with neither is deleted at once.
A check that couldn't run (a link expired, the worker down for 30 minutes) leaves the event as
the browser's rules made it, unchecked.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, true
from sqlalchemy.dialects.postgresql import insert

from app.attempts.models import ExamAttempt
from app.core.storage import EVIDENCE, Storage
from app.db.session import SessionFactory, system_session
from app.exams.models import ExamVersion
from app.proctoring.events import refresh_outcome
from app.proctoring.models import ProctoringCapture, ProctoringEvent
from workers import queues
from workers.inference_messages import JOB_TASK, Finding, InferenceJob, InferenceResult, PictureRef

WAIT_FOR_PICTURES = timedelta(minutes=2)
SEND_AGAIN_AFTER = timedelta(minutes=10)
GIVE_UP_AFTER = timedelta(minutes=30)
LINK_SECONDS = 600
SECOND_FACE = 0.2
PERSON = 0.5
PHONE = 0.5
PHONE_HIGH = 0.85
BOOK = 0.5
CONFIDENT = 0.6
LOWER = {"HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "LOW"}


def _send(job: InferenceJob) -> None:
    from workers.celery_app import enqueue

    enqueue(JOB_TASK, queues.INFERENCE_VERIFY, job=job.model_dump())


async def dispatch(
    factory: SessionFactory,
    storage: Storage,
    now: datetime | None = None,
    send: Any = _send,
    attempts: list[uuid.UUID] | None = None,
) -> int:
    """Send what's due to the inference-worker. Returns how many jobs were sent. `attempts`
    limits it to those (tests running side by side)."""
    now = now or datetime.now(UTC)
    event_scope = ProctoringEvent.attempt_id.in_(attempts) if attempts else true()
    spot_scope = ProctoringCapture.attempt_id.in_(attempts) if attempts else true()
    sent = 0
    async with system_session(factory) as session:
        events = await session.scalars(
            select(ProctoringEvent)
            .where(
                event_scope,
                ProctoringEvent.status == "PROCESSING",
                (ProctoringEvent.check_sent_at.is_(None))
                | (ProctoringEvent.check_sent_at < now - SEND_AGAIN_AFTER),
            )
            .order_by(ProctoringEvent.created_at)
            .limit(100)
        )
        for event in events:
            pictures = list(
                await session.scalars(
                    select(ProctoringCapture)
                    .where(
                        ProctoringCapture.attempt_id == event.attempt_id,
                        ProctoringCapture.event_client_id == event.client_id,
                        ProctoringCapture.deleted_at.is_(None),
                    )
                    .order_by(ProctoringCapture.taken_at)
                    .limit(3)
                )
            )
            waited = now - event.created_at
            if len(pictures) < 3 and waited < WAIT_FOR_PICTURES:
                continue  # the rest may still be on their way
            if not pictures or waited > GIVE_UP_AFTER:
                event.status = "READY"  # nothing to check with (or no answer): as the rules made it
                await refresh_outcome(session, event.attempt_id)
                continue
            event.check_sent_at = now
            send(
                InferenceJob(
                    job_id=f"event:{event.id}",
                    pictures=[_ref(storage, p) for p in pictures],
                )
            )
            sent += 1
        spots = await session.scalars(
            select(ProctoringCapture)
            .where(
                spot_scope,
                ProctoringCapture.purpose == "SPOT_CHECK",
                ProctoringCapture.checked_at.is_(None),
                ProctoringCapture.deleted_at.is_(None),
                (ProctoringCapture.check_sent_at.is_(None))
                | (ProctoringCapture.check_sent_at < now - SEND_AGAIN_AFTER),
            )
            .order_by(ProctoringCapture.created_at)
            .limit(200)
        )
        for spot in spots:
            spot.check_sent_at = now
            send(InferenceJob(job_id=f"spot:{spot.id}", pictures=[_ref(storage, spot)]))
            sent += 1
        await session.commit()
    return sent


def _ref(storage: Storage, capture: ProctoringCapture) -> PictureRef:
    return PictureRef(
        id=str(capture.id), url=storage.internal_url(EVIDENCE, capture.storage_key, LINK_SECONDS)
    )


# ----------------------------------------------------------------------------- answers


def _second_person(f: Finding) -> bool:
    main = f.faces[0].area if f.faces else 0.0
    others = [x for x in f.faces[1:] if x.area >= SECOND_FACE * main]
    people = [t for t in f.things if t.label == "person" and t.score >= PERSON]
    return bool(others) or len(people) >= 2


def confirms(kind: str, findings: list[Finding]) -> float:
    """The share of pictures that show what the event says (0: rejected)."""
    if not findings:
        return 0.0
    if kind == "FACE_ABSENT":
        hits = [f for f in findings if not f.faces]
    else:  # MULTIPLE_FACES
        hits = [f for f in findings if _second_person(f)]
    return len(hits) / len(findings)


def best(findings: list[Finding], label: str) -> float:
    return max((t.score for f in findings for t in f.things if t.label == label), default=0.0)


async def apply(factory: SessionFactory, storage: Storage, raw: dict[str, Any]) -> None:
    result = InferenceResult.model_validate(raw)
    kind, _, target = result.job_id.partition(":")
    async with system_session(factory) as session:
        if kind == "event":
            await _apply_event(session, storage, uuid.UUID(target), result)
        elif kind == "spot":
            await _apply_spot(session, storage, uuid.UUID(target), result)
        await session.commit()


async def _delete_pictures(
    session: Any, storage: Storage, pictures: list[ProctoringCapture]
) -> None:
    await storage.delete(EVIDENCE, [p.storage_key for p in pictures])
    now = datetime.now(UTC)
    for p in pictures:
        p.deleted_at = now


async def _apply_event(
    session: Any, storage: Storage, event_id: uuid.UUID, result: InferenceResult
) -> None:
    event = await session.get(ProctoringEvent, event_id, with_for_update=True)
    if event is None or event.status != "PROCESSING":
        return  # answered before
    if result.error:
        event.status = "READY"
    else:
        share = confirms(event.kind, result.findings)
        if share == 0:
            event.status = "REJECTED"
            pictures = await session.scalars(
                select(ProctoringCapture).where(
                    ProctoringCapture.attempt_id == event.attempt_id,
                    ProctoringCapture.event_client_id == event.client_id,
                    ProctoringCapture.deleted_at.is_(None),
                )
            )
            await _delete_pictures(session, storage, list(pictures))
        else:
            event.status, event.confidence = "READY", round(share, 2)
            if share < CONFIDENT:
                event.severity = LOWER[event.severity]
    await refresh_outcome(session, event.attempt_id)


async def _books_watched(session: Any, attempt: ExamAttempt) -> bool:
    if attempt.exam_version_id is None:
        snapshot = attempt.preview_snapshot or {}
        detectors = snapshot.get("settings", {}).get("proctoring_detectors") or {}
        return bool(detectors.get("books"))
    value: str | None = await session.scalar(
        select(ExamVersion.snapshot["settings"]["proctoring_detectors"]["books"].astext).where(
            ExamVersion.id == attempt.exam_version_id
        )
    )
    return value == "true"


async def _apply_spot(
    session: Any, storage: Storage, capture_id: uuid.UUID, result: InferenceResult
) -> None:
    spot = await session.get(ProctoringCapture, capture_id, with_for_update=True)
    if spot is None or spot.checked_at is not None or spot.deleted_at is not None:
        return  # answered before
    spot.checked_at = datetime.now(UTC)
    attempt = await session.get(ExamAttempt, spot.attempt_id)
    phone = best(result.findings, "cell phone")
    book = best(result.findings, "book")
    if result.error or attempt is None:
        found = None
    elif phone >= PHONE:
        found = ("PHONE_DETECTED", "HIGH" if phone >= PHONE_HIGH else "MEDIUM", phone)
    elif book >= BOOK and await _books_watched(session, attempt):
        found = ("BOOK_DETECTED", "LOW", book)
    else:
        found = None
    if found is None:
        await _delete_pictures(session, storage, [spot])
        return
    kind, severity, score = found
    event_client_id = uuid.uuid5(spot.id, kind)
    await session.execute(
        insert(ProctoringEvent)
        .values(
            id=uuid.uuid4(),
            institution_id=spot.institution_id,
            attempt_id=spot.attempt_id,
            client_id=event_client_id,
            kind=kind,
            occurred_at=spot.taken_at,
            details={},
            severity=severity,
            status="READY",
            confidence=round(score, 2),
        )
        .on_conflict_do_nothing(index_elements=["attempt_id", "client_id"])
    )
    # The picture is now evidence: out of tmp/, kept for the retention period.
    kept = spot.storage_key.removeprefix("tmp/")
    await storage.copy(EVIDENCE, spot.storage_key, kept)
    await storage.delete(EVIDENCE, [spot.storage_key])
    spot.storage_key, spot.purpose, spot.event_client_id = kept, "EVENT", event_client_id
    await refresh_outcome(session, spot.attempt_id)


async def waiting(factory: SessionFactory) -> int:
    """Events still waiting for the check (for logs)."""
    async with system_session(factory) as session:
        count = await session.scalar(
            select(func.count())
            .select_from(ProctoringEvent)
            .where(ProctoringEvent.status == "PROCESSING")
        )
        return count or 0
