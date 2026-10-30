"""Role matrix (SECURITY_AND_ACCESS.md § 11; TCK-1401): every real route, called as an admin, a
teacher and a student. A role without the route's permission gets 403; a role with it never gets
403, and nothing ever answers 500 (made-up ids and an empty body give 404 or 422, not a crash).

Public routes and the attempt-token upload route (proctoring, not a role) are left out.
"""

import re
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.passwords import hash_password
from app.authz.guards import access_table
from app.authz.permissions import role_has
from app.db.session import create_session_factory, tenant_session
from app.main import create_app
from app.users.models import User
from cli import commands
from tests.db.api_helpers import make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_start_attempt_api import bearer

ROLES = ("ADMIN", "TEACHER", "STUDENT")
NOT_A_ROLE = {"public", "authenticated", "attempt-token"}
# Routes whose success has side effects on the caller's own session; covered by their own tests.
SKIP = {"POST /api/v1/auth/logout", "POST /api/v1/auth/logout-all"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def callers(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> AsyncIterator[dict[str, dict[str, str]]]:
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(factory, f"Role matrix {uuid.uuid4().hex[:8]}")
    async with tenant_session(factory, college.id) as s:
        users = {
            role: User(
                email=f"{role.lower()}{uuid.uuid4().hex[:6]}@x.edu",
                full_name=role,
                role=role,
                status="ACTIVE",
                password_hash=hash_password("violet-tram-42-lantern"),
            )
            for role in ROLES
        }
        s.add_all(users.values())
        await s.commit()
    yield {role: bearer(user, college) for role, user in users.items()}
    await purge_institutions(migrator_engine, [college.id])


def routes() -> list[tuple[str, str, str]]:
    """(method, path, permission) for every route that needs a role's permission."""
    out = []
    for route, access in access_table(create_app(make_settings())).items():
        if access is None or access in NOT_A_ROLE or route in SKIP:
            continue
        method, path = route.split(" ", 1)
        out.append((method, path, access))
    return out


def test_every_route_answers_each_role_as_the_table_says(
    client: TestClient, callers: dict[str, dict[str, str]]
) -> None:
    wrong: list[str] = []
    for method, path, permission in routes():
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        for role in ROLES:
            body = {} if method in ("POST", "PUT", "PATCH") else None
            status = client.request(method, url, json=body, headers=callers[role]).status_code
            allowed = role_has(role, permission)
            if status >= 500:
                wrong.append(f"{method} {path} as {role}: {status}")
            elif allowed and status in (401, 403):
                wrong.append(f"{method} {path} as {role}: {status}, but it has {permission}")
            elif not allowed and status != 403:
                wrong.append(f"{method} {path} as {role}: {status}, expected 403 ({permission})")
    assert not wrong, "\n".join(wrong)
