"""Browser-check events (PRD PRC-06, PRC-10): the exam screen uploads them (the student's own
attempt; the answer says nothing back), the exam's teacher reviews them."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.proctoring import consent, events
from app.proctoring.consent import ConsentIn, ConsentView
from app.proctoring.events import DecisionIn, EventsIn, EventView

router = APIRouter(tags=["proctoring"])


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
