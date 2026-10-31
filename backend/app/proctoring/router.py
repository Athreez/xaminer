"""Proctoring events and pictures (PRD PRC-05, PRC-06, PRC-10): the exam screen uploads them (the
student's own attempt; the answer says nothing back), the exam's teacher reviews them."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis

from app.auth.dependencies import TenantDB, redis_of, session_factory_of, settings_of
from app.auth.tokens import AttemptGrant, InvalidTokenError, Principal, decode_attempt_token
from app.authz.guards import attempt_token, require
from app.authz.permissions import P
from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import SessionFactory, tenant_session
from app.images.router import AppStorage
from app.proctoring import captures, consent, events
from app.proctoring.captures import AttemptPictures, Kind, Purpose
from app.proctoring.consent import ConsentIn, ConsentView
from app.proctoring.events import DecisionIn, EventsIn, EventView

router = APIRouter(tags=["proctoring"])
_bearer = HTTPBearer(auto_error=False)


@attempt_token
async def attempt_grant(
    settings: Annotated[Settings, Depends(settings_of)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AttemptGrant:
    """The attempt token from the heartbeat (upload-only; an access token is refused)."""
    try:
        if credentials is None:
            raise InvalidTokenError("missing")
        return decode_attempt_token(credentials.credentials, settings.jwt_secret.get_secret_value())
    except InvalidTokenError as exc:
        raise AppError(
            "UNAUTHENTICATED",
            "Send the attempt token from the latest heartbeat.",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.post("/attempts/{attempt_id}/captures", status_code=status.HTTP_204_NO_CONTENT)
async def upload_capture(
    attempt_id: uuid.UUID,
    client_id: Annotated[uuid.UUID, Form()],
    kind: Annotated[Kind, Form()],
    purpose: Annotated[Purpose, Form()],
    taken_at: Annotated[datetime, Form()],
    image: Annotated[UploadFile, File(description="JPEG, PNG or WebP, at most 1 MB")],
    grant: Annotated[AttemptGrant, Depends(attempt_grant)],
    factory: Annotated[SessionFactory, Depends(session_factory_of)],
    redis: Annotated[Redis, Depends(redis_of)],
    storage: AppStorage,
    event_client_id: Annotated[uuid.UUID | None, Form()] = None,
) -> None:
    """A picture from the exam screen: of the camera for an event or a spot check, or of the
    shared screen. Needs the attempt token, not the access token. Safe to send again. Answers
    nothing about it (PRC-09)."""
    data = await image.read(captures.MAX_BYTES + 1)
    async with tenant_session(factory, grant.institution_id) as db:
        await captures.upload(
            db,
            redis,
            storage,
            grant,
            attempt_id,
            client_id=client_id,
            kind=kind,
            purpose=purpose,
            event_client_id=event_client_id,
            taken_at=taken_at,
            data=data,
        )


@router.get("/exams/{exam_id}/results/{attempt_id}/pictures")
async def attempt_pictures(
    exam_id: uuid.UUID,
    attempt_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require(P.PROCTORING_EVENT_READ))],
    db: TenantDB,
    storage: AppStorage,
) -> AttemptPictures:
    """An attempt's event and screen pictures, as links valid for 5 minutes. Each call is
    audit-logged."""
    return await captures.for_teacher(db, storage, principal, exam_id, attempt_id)


@router.post("/attempts/{attempt_id}/events", status_code=status.HTTP_204_NO_CONTENT)
async def upload_events(
    attempt_id: uuid.UUID,
    body: EventsIn,
    principal: Annotated[Principal, Depends(require(P.ATTEMPT_TAKE))],
    db: TenantDB,
) -> None:
    """What the exam screen noticed (left fullscreen, switched away, pasted from outside, more
    than one screen). Safe to send again. Answers nothing about them (PRC-09)."""
    await events.upload(db, principal, attempt_id, body)


@router.put("/proctoring-events/{event_id}/decision")
async def review_event(
    event_id: uuid.UUID,
    body: DecisionIn,
    principal: Annotated[Principal, Depends(require(P.PROCTORING_EVENT_REVIEW))],
    db: TenantDB,
) -> EventView:
    """Dismiss or flag one event of an attempt at your exam (audited). Updates the attempt's
    integrity outcome."""
    return await events.decide(db, principal, event_id, body)


@router.get("/student/exams/{exam_id}/consent", tags=["student"])
async def get_consent(
    exam_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require(P.ATTEMPT_TAKE))],
    db: TenantDB,
) -> ConsentView:
    """A proctored exam's consent text and your latest answer to it (409 `NOT_PROCTORED` when the
    exam isn't proctored)."""
    return await consent.get(db, principal, exam_id)


@router.post("/student/exams/{exam_id}/consent", tags=["student"])
async def answer_consent(
    exam_id: uuid.UUID,
    body: ConsentIn,
    principal: Annotated[Principal, Depends(require(P.ATTEMPT_TAKE))],
    db: TenantDB,
) -> ConsentView:
    """Accept or decline the consent text (recorded, audited). Starting a proctored exam needs
    your latest answer to be ACCEPTED."""
    return await consent.decide(db, principal, exam_id, body)
