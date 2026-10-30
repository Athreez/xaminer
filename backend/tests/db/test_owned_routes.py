"""Every route with an id in its path is tested against other people's items (PRD ACC-02/03/05).

When a ticket adds a route like `GET /api/v1/exams/{exam_id}`, it must add an `OwnedRoute` to
`OWNED_ROUTES` below: a `setup` that creates an item owned by `world.owner` and returns the URL.
The test then checks:

- the owner can use it (2xx),
- another user of the same role in the same institution gets 404,
- a user of the same role in another institution gets 404.

Admin routes over the whole institution (like `/users/{user_id}`) use `scope="institution"`:
there the neighbour (another admin of the same institution) is allowed too, and only the outsider
gets 404.

`per_caller=True` runs `setup` again before each caller, for routes that only work once (DELETE).
`make_body`, if given, builds a fresh request body for each call.

`test_every_id_route_is_registered` fails the build if an id route is missing here, so the check
can't be skipped as routes are added.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import Answer, AttemptQuestion, ExamAttempt
from app.auth.dependencies import CurrentPrincipal, TenantDB
from app.auth.tokens import Principal, create_access_token
from app.authz.guards import access_table, require
from app.authz.ownership import get_owned, not_found
from app.authz.permissions import P
from app.db.session import SessionFactory, create_session_factory, system_session, tenant_session
from app.exams.models import Exam, ExamAssignment, ExamQuestion, ExamVersion
from app.execution.models import CodeRun, CodingSubmission
from app.main import create_app
from app.platform.models import Institution
from app.questions.models import (
    CodingConfig,
    Question,
    QuestionVersion,
    ReferenceSolution,
    TestCase,
)
from app.results.models import Result
from app.users import service as users_service
from app.users.models import User, UserGroup, UserGroupMember
from cli import commands
from tests.db.api_helpers import SECRET, make_settings
from tests.db.question_helpers import purge_institutions


@dataclass
class World:
    factory: SessionFactory
    owner: User
    neighbour: User  # same institution, same role, not the owner
    outsider: User  # another institution, same role
    # Ids a setup made, for a request body that needs them (e.g. the question to answer).
    notes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OwnedRoute:
    route: str  # exactly as access_table prints it, e.g. "GET /api/v1/exams/{exam_id}"
    role: str  # role of the owner (and of the two other callers)
    setup: Callable[[World], Awaitable[str]]  # creates the owner's item, returns the real URL
    body: dict[str, Any] | None = field(default=None)
    scope: str = "owner"  # "owner": only the owner; "institution": anyone of that role there
    per_caller: bool = False
    make_body: Callable[[World], Awaitable[dict[str, Any]]] | None = None


async def _target(world: World, status: str = "INVITED") -> User:
    """A student in the owner's institution, for the admin user-management routes."""
    async with tenant_session(world.factory, world.owner.institution_id) as s:
        user = User(
            email=f"{uuid.uuid4().hex[:8]}@x.edu",
            full_name="Tar Get",
            role="STUDENT",
            status=status,
            password_hash="not-a-real-hash" if status == "ACTIVE" else None,
        )
        s.add(user)
        await s.commit()
        return user


def _user_url(suffix: str = "", status: str = "INVITED") -> Callable[[World], Awaitable[str]]:
    async def setup(world: World) -> str:
        return f"/api/v1/users/{(await _target(world, status)).id}{suffix}"

    return setup


async def _group(world: World, member: User | None = None) -> UserGroup:
    async with tenant_session(world.factory, world.owner.institution_id) as s:
        group = UserGroup(name=f"Group {uuid.uuid4().hex[:8]}")
        s.add(group)
        await s.flush()
        if member:
            s.add(UserGroupMember(group_id=group.id, user_id=member.id))
        await s.commit()
        return group


def _group_url(suffix: str = "") -> Callable[[World], Awaitable[str]]:
    async def setup(world: World) -> str:
        return f"/api/v1/groups/{(await _group(world)).id}{suffix}"

    return setup


async def _new_student_body(world: World) -> dict[str, Any]:
    return {"user_ids": [str((await _target(world)).id)]}


async def _new_name_body(world: World) -> dict[str, Any]:
    return {"name": f"Renamed {uuid.uuid4().hex[:8]}"}


async def _member_url(world: World) -> str:
    student = await _target(world)
    group = await _group(world, member=student)
    return f"/api/v1/groups/{group.id}/members/{student.id}"


async def _question(world: World) -> Question:
    """A private MCQ owned by `world.owner`."""
    async with tenant_session(world.factory, world.owner.institution_id) as s:
        question = Question(owner_id=world.owner.id, type="DESCRIPTIVE")
        s.add(question)
        await s.flush()
        version = QuestionVersion(
            question_id=question.id,
            version_no=1,
            body="Explain.",
            points=1,
            created_by=world.owner.id,
        )
        s.add(version)
        await s.flush()
        question.current_version_id = version.id
        await s.commit()
        return question


async def _coding_question(world: World) -> Question:
    """A private coding question owned by `world.owner`: Python allowed, one test case and a
    reference solution. The test case's id goes in `world.notes["case"]`."""
    async with tenant_session(world.factory, world.owner.institution_id) as s:
        question = Question(owner_id=world.owner.id, type="CODING")
        s.add(question)
        await s.flush()
        version = QuestionVersion(
            question_id=question.id, version_no=1, body="Add.", points=5, created_by=world.owner.id
        )
        s.add(version)
        await s.flush()
        s.add(
            CodingConfig(
                version_id=version.id,
                allowed_languages=[{"language_key": "python312", "starter_code": ""}],
            )
        )
        case = TestCase(version_id=version.id, input="1 2", expected_output="3", order_index=0)
        s.add(case)
        s.add(ReferenceSolution(version_id=version.id, language_key="python312", source="print(3)"))
        question.current_version_id = version.id
        await s.commit()
        world.notes["case"] = str(case.id)
        return question


def _coding_url(suffix: str = "", case: bool = False) -> Callable[[World], Awaitable[str]]:
    async def setup(world: World) -> str:
        question = await _coding_question(world)
        tail = f"/{world.notes['case']}" if case else ""
        return f"/api/v1/questions/{question.id}{suffix}{tail}"

    return setup


async def _order_body(world: World) -> dict[str, Any]:
    return {"ids": [world.notes["case"]]}


def _question_url(suffix: str = "") -> Callable[[World], Awaitable[str]]:
    async def setup(world: World) -> str:
        return f"/api/v1/questions/{(await _question(world)).id}{suffix}"

    return setup


def _exam_url(suffix: str = "") -> Callable[[World], Awaitable[str]]:
    async def setup(world: World) -> str:
        async with tenant_session(world.factory, world.owner.institution_id) as s:
            exam = Exam(owner_id=world.owner.id, title="Owned routes exam")
            s.add(exam)
            await s.commit()
            return f"/api/v1/exams/{exam.id}{suffix}"

    return setup


async def _assigned_student_url(world: World) -> str:
    """The owner's exam with one student assigned; the URL removes that student."""
    student = await _target(world)
    async with tenant_session(world.factory, world.owner.institution_id) as s:
        exam = Exam(owner_id=world.owner.id, title="Owned routes exam")
        s.add(exam)
        await s.flush()
        s.add(ExamAssignment(exam_id=exam.id, student_id=student.id, assigned_by=world.owner.id))
        await s.commit()
        return f"/api/v1/exams/{exam.id}/assignments/{student.id}"


async def _assign_body(world: World) -> dict[str, Any]:
    return {"student_ids": [str((await _target(world)).id)]}


async def _publishable_exam_url(world: World) -> str:
    """The owner's exam that passes the publish check: a question, a window, a student."""
    question = await _question(world)
    student = await _target(world)
    start = datetime.now(UTC) + timedelta(days=1)
    async with tenant_session(world.factory, world.owner.institution_id) as s:
        exam = Exam(
            owner_id=world.owner.id,
            title="Owned routes exam",
            open_at=start,
            close_at=start + timedelta(hours=2),
            duration_min=60,
        )
        s.add(exam)
        await s.flush()
        s.add(ExamQuestion(exam_id=exam.id, question_id=question.id, order_index=0))
        s.add(ExamAssignment(exam_id=exam.id, student_id=student.id, assigned_by=world.owner.id))
        await s.commit()
        return f"/api/v1/exams/{exam.id}/publish"


async def _assigned_exam_url(world: World) -> str:
    """A published exam assigned to `world.owner` (a student)."""
    question = await _question(world)
    start = datetime.now(UTC) - timedelta(hours=1)
    async with tenant_session(world.factory, world.owner.institution_id) as s:
        teacher = User(email=f"{uuid.uuid4().hex[:8]}@x.edu", full_name="Tea Cher", role="TEACHER")
        s.add(teacher)
        await s.flush()
        exam = Exam(
            owner_id=teacher.id,
            title="Assigned exam",
            status="PUBLISHED",
            open_at=start,
            close_at=start + timedelta(hours=3),
            duration_min=60,
        )
        s.add(exam)
        await s.flush()
        s.add(ExamQuestion(exam_id=exam.id, question_id=question.id, order_index=0))
        version = ExamVersion(
            exam_id=exam.id,
            version_no=1,
            snapshot={
                "title": "Assigned exam",
                "total_points": "0",
                "questions": [],
                "settings": {
                    "navigation_mode": "FREE",
                    "run_code_enabled": True,
                    "shuffle_questions": False,
                    "shuffle_options": False,
                },
            },
            content_hash="0" * 64,
        )
        s.add(version)
        await s.flush()
        exam.published_version_id = version.id
        s.add(ExamAssignment(exam_id=exam.id, student_id=world.owner.id, assigned_by=teacher.id))
        await s.commit()
        return f"/api/v1/student/exams/{exam.id}"


def _assigned(suffix: str = "") -> Callable[[World], Awaitable[str]]:
    async def setup(world: World) -> str:
        return f"{await _assigned_exam_url(world)}{suffix}"

    return setup


async def _attempt(world: World) -> str:
    """`world.owner` (a student) mid-way through an open exam with a written and a coding
    question. Returns the attempt id and notes both exam-question ids."""
    start = datetime.now(UTC) - timedelta(hours=1)
    async with tenant_session(world.factory, world.owner.institution_id) as s:
        teacher = User(email=f"{uuid.uuid4().hex[:8]}@x.edu", full_name="Tea Cher", role="TEACHER")
        s.add(teacher)
        await s.flush()
        exam = Exam(
            owner_id=teacher.id,
            title="Exam in progress",
            status="PUBLISHED",
            open_at=start,
            close_at=start + timedelta(hours=3),
            duration_min=60,
        )
        s.add(exam)
        await s.flush()
        snapshot_questions = []
        rows = []
        for i, kind in enumerate(("DESCRIPTIVE", "CODING")):
            question = Question(owner_id=teacher.id, type=kind)
            s.add(question)
            await s.flush()
            version = QuestionVersion(
                question_id=question.id, version_no=1, body="Q", points=1, created_by=teacher.id
            )
            s.add(version)
            await s.flush()
            question.current_version_id = version.id
            eq = ExamQuestion(
                exam_id=exam.id,
                question_id=question.id,
                order_index=i,
                pinned_version_id=version.id,
            )
            s.add(eq)
            await s.flush()
            rows.append(eq)
            entry = {
                "exam_question_id": str(eq.id),
                "version_id": str(version.id),
                "type": kind,
                "body": "Q",
                "points": "1.00",
                "negative_marks": "0.00",
                "options": [],
            }
            if kind == "CODING":
                s.add(CodingConfig(version_id=version.id))
                entry["coding"] = {  # as student_view.coding_part makes it
                    "input_format": "",
                    "output_format": "",
                    "constraints": "",
                    "languages": [{"key": "python312", "display_name": "Py", "starter_code": ""}],
                    "time_limit_ms": 1000,
                    "memory_limit_mb": 128,
                    "run_code_allowed": True,
                    "max_submissions": 10,
                    "partial_scoring": True,
                    "examples": [],
                }
            snapshot_questions.append(entry)
        exam_version = ExamVersion(
            exam_id=exam.id,
            version_no=1,
            snapshot={
                "title": "Exam in progress",
                "total_points": "2.00",
                "questions": snapshot_questions,
                "settings": {
                    "navigation_mode": "FREE",
                    "run_code_enabled": True,
                    "shuffle_questions": False,
                    "shuffle_options": False,
                },
            },
            content_hash="0" * 64,
        )
        s.add(exam_version)
        await s.flush()
        exam.published_version_id = exam_version.id
        s.add(ExamAssignment(exam_id=exam.id, student_id=world.owner.id, assigned_by=teacher.id))
        attempt = ExamAttempt(
            exam_id=exam.id,
            exam_version_id=exam_version.id,
            student_id=world.owner.id,
            deadline_at=datetime.now(UTC) + timedelta(hours=1),
            shuffle_seed=1,
        )
        s.add(attempt)
        await s.flush()
        for position, eq in enumerate(rows, start=1):
            s.add(AttemptQuestion(attempt_id=attempt.id, exam_question_id=eq.id, position=position))
        await s.commit()
        world.notes["written"], world.notes["coding"] = str(rows[0].id), str(rows[1].id)
        return str(attempt.id)


async def _run_url(world: World) -> str:
    """A Run Code result of `world.owner`'s attempt."""
    attempt_id = await _attempt(world)
    async with tenant_session(world.factory, world.owner.institution_id) as s:
        run = CodeRun(
            attempt_id=uuid.UUID(attempt_id),
            exam_question_id=uuid.UUID(world.notes["coding"]),
            language_key="python312",
            source="print(1)",
        )
        s.add(run)
        await s.commit()
        return f"/api/v1/runs/{run.id}"


async def _submission_url(world: World) -> str:
    """A code submission in `world.owner`'s attempt."""
    attempt_id = await _attempt(world)
    async with tenant_session(world.factory, world.owner.institution_id) as s:
        submission = CodingSubmission(
            attempt_id=uuid.UUID(attempt_id),
            exam_question_id=uuid.UUID(world.notes["coding"]),
            submission_no=1,
            language_key="python312",
            source="print(1)",
        )
        s.add(submission)
        await s.commit()
        return f"/api/v1/submissions/{submission.id}"


async def _submit_body(world: World) -> dict[str, Any]:
    return {"language_key": "python312", "source": "print(1)"}


async def _run_body(world: World) -> dict[str, Any]:
    return {"language_key": "python312", "source": "print(1)", "custom_input": "x"}


def _attempt_url(suffix: str = "", submitted: bool = False) -> Callable[[World], Awaitable[str]]:
    """The attempt's URL; `{written}` / `{coding}` in `suffix` become those exam-question ids."""

    async def setup(world: World) -> str:
        attempt_id = await _attempt(world)
        if submitted:
            async with tenant_session(world.factory, world.owner.institution_id) as s:
                attempt = await s.get(ExamAttempt, uuid.UUID(attempt_id))
                assert attempt is not None
                attempt.status, attempt.submitted_at = "SUBMITTED", datetime.now(UTC)
                await s.commit()
        return f"/api/v1/attempts/{attempt_id}" + suffix.format(**world.notes)

    return setup


async def _answer_body(world: World) -> dict[str, Any]:
    return {
        "answers": [
            {"exam_question_id": world.notes["written"], "text_answer": "x", "client_revision": 1}
        ]
    }


def _managed_attempt_url(suffix: str) -> Callable[[World], Awaitable[str]]:
    """A student's attempt at an exam owned by `world.owner` (a teacher)."""

    async def setup(world: World) -> str:
        start = datetime.now(UTC) - timedelta(minutes=10)
        async with tenant_session(world.factory, world.owner.institution_id) as s:
            student = User(email=f"{uuid.uuid4().hex[:8]}@x.edu", full_name="Stu", role="STUDENT")
            s.add(student)
            exam = Exam(
                owner_id=world.owner.id,
                title="Managed exam",
                status="PUBLISHED",
                open_at=start,
                close_at=start + timedelta(hours=3),
                duration_min=60,
            )
            s.add(exam)
            await s.flush()
            version = ExamVersion(exam_id=exam.id, version_no=1, snapshot={}, content_hash="0" * 64)
            s.add(version)
            await s.flush()
            exam.published_version_id = version.id
            attempt = ExamAttempt(
                exam_id=exam.id,
                exam_version_id=version.id,
                student_id=student.id,
                started_at=start,
                deadline_at=start + timedelta(minutes=60),
                shuffle_seed=1,
            )
            s.add(attempt)
            await s.commit()
            return f"/api/v1/attempts/{attempt.id}{suffix}"

    return setup


def _draft_with_question_url(suffix: str) -> Callable[[World], Awaitable[str]]:
    """A draft exam of `world.owner` (a teacher) with one question in it."""

    async def setup(world: World) -> str:
        question = await _question(world)
        async with tenant_session(world.factory, world.owner.institution_id) as s:
            exam = Exam(owner_id=world.owner.id, title="Draft to preview")
            s.add(exam)
            await s.flush()
            s.add(ExamQuestion(exam_id=exam.id, question_id=question.id, order_index=0))
            await s.commit()
            return f"/api/v1/exams/{exam.id}{suffix}"

    return setup


def _graded_url(path: str, released: bool = True) -> Callable[[World], Awaitable[str]]:
    """An ended, fully graded attempt with its result. A TEACHER `world.owner` owns the exam; a
    STUDENT one took it. `path` takes {exam}, {attempt} and {question} (the written question)."""

    async def setup(world: World) -> str:
        start = datetime.now(UTC) - timedelta(hours=2)
        async with tenant_session(world.factory, world.owner.institution_id) as s:
            other_role = "STUDENT" if world.owner.role == "TEACHER" else "TEACHER"
            other = User(email=f"{uuid.uuid4().hex[:8]}@x.edu", full_name="Other", role=other_role)
            s.add(other)
            await s.flush()
            teacher, student = (
                (world.owner, other) if world.owner.role == "TEACHER" else (other, world.owner)
            )
            question = Question(owner_id=teacher.id, type="DESCRIPTIVE")
            s.add(question)
            await s.flush()
            s.add(
                QuestionVersion(
                    question_id=question.id,
                    version_no=1,
                    body="Explain.",
                    points=5,
                    created_by=teacher.id,
                )
            )
            exam = Exam(
                owner_id=teacher.id,
                title="Graded exam",
                status="PUBLISHED",
                open_at=start,
                close_at=start + timedelta(hours=1),
                duration_min=60,
            )
            s.add(exam)
            await s.flush()
            eq = ExamQuestion(exam_id=exam.id, question_id=question.id, order_index=0)
            s.add(eq)
            await s.flush()
            snapshot = {
                "settings": {},
                "total_points": "5",
                "questions": [
                    {
                        "exam_question_id": str(eq.id),
                        "type": "DESCRIPTIVE",
                        "points": "5",
                        "body": "Explain.",
                        "options": [],
                        "rubric": None,
                    }
                ],
            }
            version = ExamVersion(
                exam_id=exam.id, version_no=1, snapshot=snapshot, content_hash="0" * 64
            )
            s.add(version)
            await s.flush()
            exam.published_version_id = version.id
            attempt = ExamAttempt(
                exam_id=exam.id,
                exam_version_id=version.id,
                student_id=student.id,
                status="SUBMITTED",
                grading_status="COMPLETE",
                started_at=start,
                deadline_at=start + timedelta(minutes=60),
                submitted_at=start + timedelta(minutes=30),
                shuffle_seed=1,
            )
            s.add(attempt)
            await s.flush()
            s.add(
                Answer(
                    attempt_id=attempt.id,
                    exam_question_id=eq.id,
                    text_answer="An answer.",
                    manual_score=Decimal("3"),
                    score=Decimal("3"),
                )
            )
            s.add(
                Result(
                    attempt_id=attempt.id,
                    total_score=Decimal("3"),
                    max_score=Decimal("5"),
                    percentage=Decimal("60"),
                    per_question=[],
                    released_at=datetime.now(UTC) if released else None,
                )
            )
            await s.commit()
            return "/api/v1" + path.format(exam=exam.id, attempt=attempt.id, question=eq.id)

    return setup


USERS = "/api/v1/users/{user_id}"
EXAMS = "/api/v1/exams/{exam_id}"
QUESTIONS = "/api/v1/questions/{question_id}"
GROUPS = "/api/v1/groups/{group_id}"


# Add one entry per id route as tickets introduce them.
OWNED_ROUTES: list[OwnedRoute] = [
    OwnedRoute(f"GET {USERS}", "ADMIN", _user_url(), scope="institution"),
    OwnedRoute(
        f"PATCH {USERS}", "ADMIN", _user_url(), body={"full_name": "New Name"}, scope="institution"
    ),
    OwnedRoute(f"POST {USERS}/deactivate", "ADMIN", _user_url("/deactivate"), scope="institution"),
    OwnedRoute(f"POST {USERS}/reactivate", "ADMIN", _user_url("/reactivate"), scope="institution"),
    OwnedRoute(
        f"POST {USERS}/resend-invite", "ADMIN", _user_url("/resend-invite"), scope="institution"
    ),
    OwnedRoute(
        f"POST {USERS}/password-reset",
        "ADMIN",
        _user_url("/password-reset", "ACTIVE"),
        scope="institution",
    ),
    OwnedRoute(f"POST {USERS}/unlock", "ADMIN", _user_url("/unlock"), scope="institution"),
    OwnedRoute(f"GET {QUESTIONS}", "TEACHER", _question_url()),
    OwnedRoute(f"PATCH {QUESTIONS}", "TEACHER", _question_url(), body={"body": "Explain why."}),
    OwnedRoute(f"GET {QUESTIONS}/preview", "TEACHER", _question_url("/preview")),
    OwnedRoute(f"POST {QUESTIONS}/copy", "TEACHER", _question_url("/copy")),
    OwnedRoute(f"POST {QUESTIONS}/archive", "TEACHER", _question_url("/archive")),
    OwnedRoute(f"POST {QUESTIONS}/restore", "TEACHER", _question_url("/restore")),
    OwnedRoute(
        f"PUT {QUESTIONS}/coding",
        "TEACHER",
        _coding_url("/coding"),
        body={"allowed_languages": [{"language_key": "python312"}]},
    ),
    OwnedRoute(f"GET {QUESTIONS}/test-cases", "TEACHER", _coding_url("/test-cases")),
    OwnedRoute(
        f"POST {QUESTIONS}/test-cases",
        "TEACHER",
        _coding_url("/test-cases"),
        body={"expected_output": "1"},
    ),
    OwnedRoute(
        f"PUT {QUESTIONS}/test-cases/order",
        "TEACHER",
        _coding_url("/test-cases/order"),
        per_caller=True,
        make_body=_order_body,
    ),
    OwnedRoute(
        f"PATCH {QUESTIONS}/test-cases/{{case_id}}",
        "TEACHER",
        _coding_url("/test-cases", case=True),
        body={"weight": 2},
    ),
    OwnedRoute(
        f"DELETE {QUESTIONS}/test-cases/{{case_id}}",
        "TEACHER",
        _coding_url("/test-cases", case=True),
        per_caller=True,
    ),
    OwnedRoute(
        f"PUT {QUESTIONS}/reference-solutions/{{language_key}}",
        "TEACHER",
        _coding_url("/reference-solutions/python312"),
        body={"source": "print(1 + 2)"},
    ),
    OwnedRoute(
        f"DELETE {QUESTIONS}/reference-solutions/{{language_key}}",
        "TEACHER",
        _coding_url("/reference-solutions/python312"),
        per_caller=True,
    ),
    OwnedRoute(f"POST {QUESTIONS}/validate", "TEACHER", _coding_url("/validate")),
    OwnedRoute(f"GET {EXAMS}", "TEACHER", _exam_url()),
    OwnedRoute(f"PATCH {EXAMS}", "TEACHER", _exam_url(), body={"title": "Renamed"}),
    OwnedRoute(f"DELETE {EXAMS}", "TEACHER", _exam_url(), per_caller=True),
    OwnedRoute(f"POST {EXAMS}/archive", "TEACHER", _exam_url("/archive")),
    OwnedRoute(f"GET {EXAMS}/questions", "TEACHER", _exam_url("/questions")),
    OwnedRoute(f"GET {EXAMS}/assignments", "TEACHER", _exam_url("/assignments")),
    OwnedRoute(
        f"POST {EXAMS}/assignments", "TEACHER", _exam_url("/assignments"), make_body=_assign_body
    ),
    OwnedRoute(
        f"DELETE {EXAMS}/assignments/{{student_id}}",
        "TEACHER",
        _assigned_student_url,
        per_caller=True,
    ),
    OwnedRoute(f"GET {EXAMS}/student-choices", "TEACHER", _exam_url("/student-choices")),
    OwnedRoute(f"GET {EXAMS}/publish-check", "TEACHER", _exam_url("/publish-check")),
    OwnedRoute(
        f"POST {EXAMS}/preview-attempt",
        "TEACHER",
        _draft_with_question_url("/preview-attempt"),
    ),
    OwnedRoute(f"POST {EXAMS}/publish", "TEACHER", _publishable_exam_url, per_caller=True),
    OwnedRoute(
        f"PUT {EXAMS}/questions", "TEACHER", _exam_url("/questions"), body={"questions": []}
    ),
    OwnedRoute("GET /api/v1/student/exams/{exam_id}", "STUDENT", _assigned_exam_url),
    OwnedRoute("POST /api/v1/student/exams/{exam_id}/attempts", "STUDENT", _assigned("/attempts")),
    OwnedRoute("GET /api/v1/attempts/{attempt_id}", "STUDENT", _attempt_url()),
    OwnedRoute(
        "POST /api/v1/attempts/{attempt_id}/questions/{exam_question_id}/runs",
        "STUDENT",
        _attempt_url("/questions/{coding}/runs"),
        make_body=_run_body,
    ),
    OwnedRoute("GET /api/v1/runs/{run_id}", "STUDENT", _run_url),
    OwnedRoute(
        "POST /api/v1/attempts/{attempt_id}/questions/{exam_question_id}/submissions",
        "STUDENT",
        _attempt_url("/questions/{coding}/submissions"),
        make_body=_submit_body,
    ),
    OwnedRoute(
        "GET /api/v1/attempts/{attempt_id}/questions/{exam_question_id}/submissions",
        "STUDENT",
        _attempt_url("/questions/{coding}/submissions"),
    ),
    OwnedRoute("GET /api/v1/submissions/{submission_id}", "STUDENT", _submission_url),
    OwnedRoute("POST /api/v1/attempts/{attempt_id}/submit", "STUDENT", _attempt_url("/submit")),
    OwnedRoute(
        "POST /api/v1/attempts/{attempt_id}/extend",
        "TEACHER",
        _managed_attempt_url("/extend"),
        body={"minutes": 5, "reason": "Wi-Fi dropped"},
    ),
    OwnedRoute(
        "POST /api/v1/attempts/{attempt_id}/force-submit",
        "TEACHER",
        _managed_attempt_url("/force-submit"),
        body={"reason": "Left the room"},
    ),
    OwnedRoute(
        "POST /api/v1/attempts/{attempt_id}/void",
        "TEACHER",
        _managed_attempt_url("/void"),
        body={"reason": "Wrong student"},
    ),
    OwnedRoute(
        "GET /api/v1/attempts/{attempt_id}/receipt",
        "STUDENT",
        _attempt_url("/receipt", submitted=True),
    ),
    OwnedRoute(
        "POST /api/v1/attempts/{attempt_id}/heartbeat",
        "STUDENT",
        _attempt_url("/heartbeat"),
        body={"unsynced": 0},
    ),
    OwnedRoute(
        "PUT /api/v1/attempts/{attempt_id}/answers",
        "STUDENT",
        _attempt_url("/answers"),
        make_body=_answer_body,
    ),
    OwnedRoute(
        "PUT /api/v1/attempts/{attempt_id}/flags/{exam_question_id}",
        "STUDENT",
        _attempt_url("/flags/{written}"),
        body={"marked": True},
    ),
    OwnedRoute(
        "PUT /api/v1/attempts/{attempt_id}/drafts/{exam_question_id}",
        "STUDENT",
        _attempt_url("/drafts/{coding}"),
        body={"language_key": "python312", "source": "print(1)", "client_revision": 1},
    ),
    OwnedRoute(
        "GET /api/v1/exams/{exam_id}/grading", "TEACHER", _graded_url("/exams/{exam}/grading")
    ),
    OwnedRoute(
        "GET /api/v1/exams/{exam_id}/results", "TEACHER", _graded_url("/exams/{exam}/results")
    ),
    OwnedRoute(
        "GET /api/v1/exams/{exam_id}/results/{attempt_id}",
        "TEACHER",
        _graded_url("/exams/{exam}/results/{attempt}"),
    ),
    OwnedRoute(
        "POST /api/v1/exams/{exam_id}/results/release",
        "TEACHER",
        _graded_url("/exams/{exam}/results/release", released=False),
    ),
    OwnedRoute(
        "PUT /api/v1/attempts/{attempt_id}/answers/{exam_question_id}/mark",
        "TEACHER",
        _graded_url("/attempts/{attempt}/answers/{question}/mark"),
        body={"score": "4", "reason": "Re-read"},
    ),
    OwnedRoute(
        "GET /api/v1/student/results/{attempt_id}",
        "STUDENT",
        _graded_url("/student/results/{attempt}"),
    ),
    OwnedRoute(f"GET {GROUPS}", "TEACHER", _group_url(), scope="institution"),
    OwnedRoute(
        f"PATCH {GROUPS}",
        "ADMIN",
        _group_url(),
        scope="institution",
        per_caller=True,
        make_body=_new_name_body,
    ),
    OwnedRoute(f"DELETE {GROUPS}", "ADMIN", _group_url(), scope="institution", per_caller=True),
    OwnedRoute(
        f"POST {GROUPS}/members",
        "ADMIN",
        _group_url("/members"),
        scope="institution",
        make_body=_new_student_body,
    ),
    OwnedRoute(
        f"DELETE {GROUPS}/members/{{user_id}}",
        "ADMIN",
        _member_url,
        scope="institution",
        per_caller=True,
    ),
]


def id_routes() -> list[str]:
    table = access_table(create_app(make_settings()))
    return sorted(r for r, access in table.items() if "{" in r and access != "public")


def test_every_id_route_is_registered() -> None:
    registered = {case.route for case in OWNED_ROUTES}
    missing = [route for route in id_routes() if route not in registered]
    assert not missing, (
        "Routes with an id in the path need an ownership test case in OWNED_ROUTES: "
        + ", ".join(missing)
    )


def test_registered_routes_exist() -> None:
    existing = set(id_routes())
    stale = [case.route for case in OWNED_ROUTES if case.route not in existing]
    assert not stale, f"OWNED_ROUTES lists routes that no longer exist: {stale}"


# ----------------------------------------------------------------------------- the actual check


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def factory(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    async with system_session(factory) as s:
        ids = list(
            await s.scalars(
                select(Institution.id).where(Institution.name.like("Owned routes test%"))
            )
        )
    # Published exams and locked question versions need the owner's clean-up.
    await purge_institutions(migrator_engine, ids)


async def _user(factory: SessionFactory, institution: Institution, role: str) -> User:
    async with tenant_session(factory, institution.id) as s:
        user = User(email=f"{uuid.uuid4().hex[:8]}@x.edu", full_name="Some One", role=role)
        s.add(user)
        await s.commit()
        return user


def _bearer(user: User) -> dict[str, str]:
    principal = Principal(user.id, user.institution_id, user.role)
    return {"Authorization": f"Bearer {create_access_token(principal, SECRET, 15)}"}


async def statuses(case: OwnedRoute, client: TestClient, factory: SessionFactory) -> list[int]:
    """Status codes for (owner, same-institution neighbour, other-institution outsider)."""
    home = await commands.create_institution(factory, f"Owned routes test {uuid.uuid4().hex[:8]}")
    away = await commands.create_institution(factory, f"Owned routes test {uuid.uuid4().hex[:8]}")
    world = World(
        factory=factory,
        owner=await _user(factory, home, case.role),
        neighbour=await _user(factory, home, case.role),
        outsider=await _user(factory, away, case.role),
    )
    method = case.route.split(" ", 1)[0]
    url = await case.setup(world)
    codes = []
    for user in (world.owner, world.neighbour, world.outsider):
        if case.per_caller and user is not world.owner:
            url = await case.setup(world)
        body = await case.make_body(world) if case.make_body else case.body
        codes.append(client.request(method, url, json=body, headers=_bearer(user)).status_code)
    return codes


def only_owner_allowed(codes: list[int]) -> bool:
    owner, neighbour, outsider = codes
    return owner < 400 and neighbour == 404 and outsider == 404


def only_institution_allowed(codes: list[int]) -> bool:
    owner, neighbour, outsider = codes
    return owner < 400 and neighbour < 400 and outsider == 404


@pytest.mark.parametrize("case", OWNED_ROUTES, ids=lambda c: c.route)
async def test_only_the_owner_can_reach_it(
    case: OwnedRoute,
    client: TestClient,
    factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users_service, "queue_email", lambda email: None)
    codes = await statuses(case, client, factory)
    check = only_institution_allowed if case.scope == "institution" else only_owner_allowed
    assert check(codes), f"{case.route} ({case.scope}): owner/neighbour/outsider got {codes}"


# ----------------------------------------------------------------------------- the checker works


async def _own_user_url(world: World) -> str:
    return f"/api/v1/_demo/users/{world.owner.id}"


async def _leaky_user_url(world: World) -> str:
    return f"/api/v1/_demo/leaky/{world.owner.id}"


async def test_the_check_passes_a_correct_route_and_catches_a_leaky_one(
    factory: SessionFactory,
) -> None:
    app = create_app(make_settings())

    @app.get("/api/v1/_demo/users/{user_id}", dependencies=[Depends(require(P.ACCOUNT_SELF))])
    async def correct(user_id: uuid.UUID, principal: CurrentPrincipal, db: TenantDB) -> str:
        user = await get_owned(
            db, User, user_id, principal, owned=lambda u: u.id == principal.user_id
        )
        return user.email

    @app.get("/api/v1/_demo/leaky/{user_id}", dependencies=[Depends(require(P.ACCOUNT_SELF))])
    async def leaky(user_id: uuid.UUID, db: TenantDB) -> str:
        user = await db.get(User, user_id)  # forgot get_owned: no ownership check
        if user is None:
            raise not_found()
        return user.email

    with TestClient(app) as demo_client:
        good = await statuses(
            OwnedRoute("GET /api/v1/_demo/users/{user_id}", "STUDENT", _own_user_url),
            demo_client,
            factory,
        )
        bad = await statuses(
            OwnedRoute("GET /api/v1/_demo/leaky/{user_id}", "STUDENT", _leaky_user_url),
            demo_client,
            factory,
        )
    assert good == [200, 404, 404]
    assert not only_owner_allowed(bad)  # the neighbour got in: the checker flags it
    assert bad[1] == 200 and bad[2] == 404  # institution filter still stopped the outsider
