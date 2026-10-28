"""CSV import of users through the real HTTP API (PRD USR-03)."""

import time
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.models import AuditLog
from app.auth.models import AuthToken
from app.auth.tokens import Principal, create_access_token
from app.db.session import SessionFactory, create_session_factory, system_session, tenant_session
from app.main import create_app
from app.notifications.emails import Email
from app.platform.models import Institution
from app.users import csv_import
from app.users.models import User
from cli import commands
from tests.db.api_helpers import SECRET, make_settings

URL = "/api/v1/users/import"


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[Email]:
    sent: list[Email] = []
    monkeypatch.setattr(csv_import, "queue_email", sent.append)
    return sent


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def factory(app_engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    async with system_session(factory) as s:
        ids = select(Institution.id).where(Institution.name.like("CSV test%"))
        for model in (AuthToken, User):
            await s.execute(delete(model).where(model.institution_id.in_(ids)))
        await s.execute(delete(Institution).where(Institution.name.like("CSV test%")))
        await s.commit()


@pytest.fixture
async def college(factory: SessionFactory) -> Institution:
    return await commands.create_institution(factory, f"CSV test {uuid.uuid4().hex[:8]}")


async def member(
    factory: SessionFactory, college: Institution, role: str, **fields: str
) -> dict[str, str]:
    async with tenant_session(factory, college.id) as s:
        user = User(
            email=fields.get("email", f"u{uuid.uuid4().hex[:8]}@abc.edu"),
            full_name="Some One",
            role=role,
            roll_no=fields.get("roll_no"),
        )
        s.add(user)
        await s.commit()
    principal = Principal(user.id, college.id, role)
    return {"Authorization": f"Bearer {create_access_token(principal, SECRET, 15)}"}


async def user_count(factory: SessionFactory, college: Institution) -> int:
    async with tenant_session(factory, college.id) as s:
        return await s.scalar(select(func.count()).select_from(User)) or 0


MIXED = """﻿Email,Name,Role,Roll No
ravi@abc.edu,Ravi Kumar,student,CSE-001
taken@abc.edu,Old User,Student,
asha@abc.edu,Asha Rao,TEACHER,

not-an-email,Bad Email,Student,
,No Email,Student,
meena@abc.edu,,Student,
kiran@abc.edu,Kiran,Principal,
RAVI@abc.edu,Ravi Again,Student,
dev@abc.edu,Dev,Student,CSE-001
old@abc.edu,Roll Clash,Student,CSE-900
"""


async def test_preview_then_import(
    client: TestClient, factory: SessionFactory, college: Institution, outbox: list[Email]
) -> None:
    headers = await member(factory, college, "ADMIN", email="taken@abc.edu")
    await member(factory, college, "STUDENT", roll_no="CSE-900")
    before = await user_count(factory, college)

    preview = client.post(URL, json={"csv": MIXED, "dry_run": True}, headers=headers)
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert (result["total"], result["ready"], result["skipped"], result["failed"]) == (10, 2, 1, 7)
    by_line = {r["row"]: (r["status"], r["message"]) for r in result["rows"]}
    assert by_line[2] == ("READY", None)
    assert by_line[3] == ("SKIPPED", "Already has an account")
    assert by_line[4] == ("READY", None)  # line 5 is blank and ignored
    assert by_line[6] == ("ERROR", "Email is not valid")
    assert by_line[7] == ("ERROR", "Email is missing")
    assert by_line[8] == ("ERROR", "Name is missing")
    assert by_line[9] == ("ERROR", "Role must be Admin, Teacher or Student")
    assert by_line[10] == ("ERROR", "Same email as line 2")
    assert by_line[11] == ("ERROR", "Same roll no. as line 2")
    assert by_line[12][1] == "Roll no. CSE-900 is already used by another user"
    assert await user_count(factory, college) == before  # preview changes nothing
    assert outbox == []

    done = client.post(URL, json={"csv": MIXED, "dry_run": False}, headers=headers).json()
    assert (done["ready"], done["skipped"], done["failed"]) == (2, 1, 7)
    assert {r["email"] for r in done["rows"] if r["status"] == "IMPORTED"} == {
        "ravi@abc.edu",
        "asha@abc.edu",
    }
    assert sorted(e.to for e in outbox) == ["asha@abc.edu", "ravi@abc.edu"]
    assert await user_count(factory, college) == before + 2
    async with tenant_session(factory, college.id) as s:
        asha = await s.scalar(select(User).where(User.email == "asha@abc.edu"))
        assert asha is not None and asha.role == "TEACHER" and asha.status == "INVITED"
        summary = await s.scalar(select(AuditLog).where(AuditLog.action == "user.csv_imported"))
        assert summary is not None
        assert summary.changes == {"imported": 2, "skipped": 1, "failed": 7}
        invited = await s.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "user.invited")
        )
        assert invited == 2

    again = client.post(URL, json={"csv": MIXED, "dry_run": False}, headers=headers).json()
    assert (again["ready"], again["skipped"]) == (0, 3)  # running it twice adds nobody


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "The file is empty."),
        ("email,role\na@abc.edu,Student\n", "Missing: full name"),
        ("email,name,role\n\n\n", "has a header but no users"),
        ('email,name,role\n"a@abc.edu,Ann,Student\n', "can't be read"),
    ],
    ids=["empty", "missing-column", "header-only", "broken-quote"],
)
async def test_unreadable_files(
    client: TestClient, factory: SessionFactory, college: Institution, text: str, message: str
) -> None:
    headers = await member(factory, college, "ADMIN")
    response = client.post(URL, json={"csv": text, "dry_run": True}, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_FILE"
    assert message in response.json()["error"]["message"]


async def test_size_limits(
    client: TestClient, factory: SessionFactory, college: Institution
) -> None:
    headers = await member(factory, college, "ADMIN")
    rows = "".join(f"s{i}@abc.edu,Student {i},Student\n" for i in range(2001))
    too_many = client.post(
        URL, json={"csv": "email,name,role\n" + rows, "dry_run": True}, headers=headers
    )
    assert too_many.status_code == 422 and "more than 2,000" in too_many.json()["error"]["message"]
    huge = "email,name,role\n" + "x" * 1_000_001
    assert client.post(URL, json={"csv": huge, "dry_run": True}, headers=headers).status_code == 422


async def test_two_thousand_rows_import(
    client: TestClient, factory: SessionFactory, college: Institution, outbox: list[Email]
) -> None:
    headers = await member(factory, college, "ADMIN")
    rows = "".join(f"s{i}@abc.edu,Student {i},Student,R-{i:04}\n" for i in range(2000))
    started = time.monotonic()
    response = client.post(
        URL,
        json={"csv": "email,full name,role,roll no\n" + rows, "dry_run": False},
        headers=headers,
    )
    elapsed = time.monotonic() - started
    assert response.status_code == 200, response.text
    assert response.json()["ready"] == 2000 and len(outbox) == 2000
    assert await user_count(factory, college) == 2001
    assert elapsed < 30, f"took {elapsed:.1f}s"


async def test_only_admins(
    client: TestClient, factory: SessionFactory, college: Institution
) -> None:
    headers = await member(factory, college, "TEACHER")
    body = {"csv": "email,name,role\na@abc.edu,A,Student\n", "dry_run": True}
    assert client.post(URL, json=body, headers=headers).status_code == 403
