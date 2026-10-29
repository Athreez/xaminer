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
from typing import Any

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.dependencies import CurrentPrincipal, TenantDB
from app.auth.models import AuthToken, RefreshToken
from app.auth.tokens import Principal, create_access_token
from app.authz.guards import access_table, require
from app.authz.ownership import get_owned, not_found
from app.authz.permissions import P
from app.db.session import SessionFactory, create_session_factory, system_session, tenant_session
from app.main import create_app
from app.platform.models import Institution
from app.questions.models import Question, QuestionVersion
from app.users import service as users_service
from app.users.models import User, UserGroup, UserGroupMember
from cli import commands
from tests.db.api_helpers import SECRET, make_settings


@dataclass
class World:
    factory: SessionFactory
    owner: User
    neighbour: User  # same institution, same role, not the owner
    outsider: User  # another institution, same role


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


def _question_url(suffix: str = "") -> Callable[[World], Awaitable[str]]:
    async def setup(world: World) -> str:
        return f"/api/v1/questions/{(await _question(world)).id}{suffix}"

    return setup


USERS = "/api/v1/users/{user_id}"
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
async def factory(app_engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    async with system_session(factory) as s:
        ids = select(Institution.id).where(Institution.name.like("Owned routes test%"))
        # Deleting a question removes its versions and options too.
        for model in (AuthToken, RefreshToken, UserGroupMember, UserGroup, Question, User):
            await s.execute(delete(model).where(model.institution_id.in_(ids)))
        await s.execute(delete(Institution).where(Institution.name.like("Owned routes test%")))
        await s.commit()


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
