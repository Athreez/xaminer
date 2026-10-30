"""Notifications (PRD NOT-02, NOT-03; TCK-1301, TCK-1303): created on each event (exam assigned,
result released, result changed), emails only to active accounts and only after the commit; each
user reads and marks only their own."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.passwords import hash_password
from app.db.session import tenant_session
from app.grading.objective import grade
from app.main import create_app
from app.notifications.emails import Email
from app.users.models import User
from tests.db.api_helpers import make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_results_api import all_right_but_the_essay
from tests.db.test_start_attempt_api import World, bearer, build


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False)
        yield w
    await purge_institutions(migrator_engine, [college.id])


def inbox(world: World, me: dict[str, str]) -> dict[str, Any]:
    response = world.client.get("/api/v1/notifications", headers=me)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def activate(world: World, user_id: uuid.UUID) -> None:
    async with tenant_session(world.factory, world.college.id) as s:
        await s.execute(
            update(User)
            .where(User.id == user_id)
            .values(status="ACTIVE", password_hash=hash_password("violet-tram-42-lantern"))
        )
        await s.commit()


async def test_exam_assigned_on_publish_and_on_a_later_assignment(
    world: World, notification_emails: list[Email]
) -> None:
    # Published in build(): the (invited) student is told in the app; no email, they can't log in.
    (n,) = inbox(world, world.me)["items"]
    assert (n["kind"], n["title"], n["read"]) == ("EXAM_ASSIGNED", "New exam: Mid-term", False)
    assert n["link"] == f"/student/exams/{world.exam_id}"
    assert notification_emails == []

    async with tenant_session(world.factory, world.college.id) as s:
        late = User(
            email=f"late{uuid.uuid4().hex[:6]}@abc.edu", full_name="Late Comer", role="STUDENT"
        )
        s.add(late)
        await s.commit()
    await activate(world, late.id)
    added = world.client.post(
        f"/api/v1/exams/{world.exam_id}/assignments",
        json={"student_ids": [str(late.id)]},
        headers=world.teacher,
    )
    assert added.status_code == 200, added.text
    assert [n["kind"] for n in inbox(world, bearer(late, world.college))["items"]] == [
        "EXAM_ASSIGNED"
    ]
    (email,) = notification_emails
    assert email.to == late.email and email.subject == "New exam: Mid-term"
    assert f"/student/exams/{world.exam_id}" in email.text


async def test_result_released_and_changed(world: World, notification_emails: list[Email]) -> None:
    await activate(world, world.student.id)
    attempt = await all_right_but_the_essay(world)
    mark = f"/api/v1/attempts/{attempt['id']}/answers/{attempt['essay']}/mark"
    world.client.put(mark, json={"score": "4"}, headers=world.teacher)
    assert inbox(world, world.me)["unread"] == 1  # only the assignment so far

    world.client.post(f"/api/v1/exams/{world.exam_id}/results/release", headers=world.teacher)
    items = inbox(world, world.me)["items"]
    assert items[0]["kind"] == "RESULT_RELEASED"
    assert items[0]["link"] == f"/student/results/{attempt['id']}"
    (email,) = notification_emails
    assert email.to == world.student.email and email.subject == "Your result: Mid-term"

    world.client.put(mark, json={"score": "5", "reason": "Re-read"}, headers=world.teacher)
    changed = inbox(world, world.me)["items"][0]
    assert (changed["kind"], changed["body"]) == ("RESULT_CHANGED", "9.00 → 10.00. Re-read")
    assert len(notification_emails) == 1  # a change is in-app only


async def test_read_one_read_all_and_only_your_own(world: World) -> None:
    (n,) = inbox(world, world.me)["items"]
    assert (
        world.client.post(
            f"/api/v1/notifications/{n['id']}/read", headers=world.teacher
        ).status_code
        == 404
    )
    assert (
        world.client.post(f"/api/v1/notifications/{n['id']}/read", headers=world.me).status_code
        == 204
    )
    assert inbox(world, world.me)["unread"] == 0
    assert world.client.post("/api/v1/notifications/read-all", headers=world.me).status_code == 204
    assert inbox(world, world.teacher)["items"] == []  # the teacher has none


async def test_a_result_released_on_submit_is_notified(world: World) -> None:
    """A results-on-submit exam: the result is released (and notified) as grading completes."""
    mine = world.client.get(
        "/api/v1/questions", params={"owner": "mine", "type": "MCQ"}, headers=world.teacher
    ).json()["data"]
    now = datetime.now(UTC)
    exam = world.client.post(
        "/api/v1/exams",
        json={
            "title": "Quiz",
            "open_at": (now - timedelta(minutes=5)).isoformat(),
            "close_at": (now + timedelta(hours=1)).isoformat(),
            "duration_min": 10,
            "release_policy": "ON_SUBMIT",
        },
        headers=world.teacher,
    ).json()
    url = f"/api/v1/exams/{exam['id']}"
    world.client.put(
        f"{url}/questions",
        json={"questions": [{"question_id": mine[0]["id"]}]},
        headers=world.teacher,
    )
    world.client.post(
        f"{url}/assignments", json={"student_ids": [str(world.student.id)]}, headers=world.teacher
    )
    assert world.client.post(f"{url}/publish", headers=world.teacher).status_code == 200
    attempt = world.client.post(
        f"/api/v1/student/exams/{exam['id']}/attempts", headers=world.me
    ).json()
    world.client.post(f"/api/v1/attempts/{attempt['id']}/submit", headers=world.me)
    await grade(world.factory, uuid.UUID(attempt["id"]))  # unanswered: complete at once
    latest = inbox(world, world.me)["items"][0]
    assert (latest["kind"], latest["title"]) == ("RESULT_RELEASED", "Result out: Quiz")
