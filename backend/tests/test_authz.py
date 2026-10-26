"""Permissions (SECURITY_AND_ACCESS.md § 3): the role table and the every-route-declares rule."""

import uuid

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.tokens import Principal, create_access_token
from app.authz.guards import PUBLIC, access_table, assert_routes_declared, require
from app.authz.permissions import ROLE_PERMISSIONS, P, Permission, role_has
from app.core.config import Settings
from app.main import create_app

SECRET = "test-signing-secret-that-is-long-enough-123"


# ----------------------------------------------------------------------------- every route declares


def test_every_real_route_declares_access() -> None:
    table = access_table(create_app(Settings(environment="test")))
    assert table, "no routes found"
    assert all(access is not None for access in table.values()), table
    assert table["POST /api/v1/auth/login"] == "public"
    assert table["GET /api/v1/auth/me"] == "account:self"


def test_undeclared_route_on_an_included_router_is_refused() -> None:
    app = FastAPI()
    router = APIRouter(prefix="/things")

    @router.get("/secret")
    async def forgot_the_check() -> dict[str, str]:
        return {}

    app.include_router(router, prefix="/api/v1")
    with pytest.raises(RuntimeError, match=r"GET /api/v1/things/secret"):
        assert_routes_declared(app)


def test_undeclared_route_directly_on_the_app_is_refused() -> None:
    app = FastAPI()

    @app.post("/open")
    async def forgot_the_check() -> None:
        pass

    with pytest.raises(RuntimeError, match=r"POST /open"):
        assert_routes_declared(app)


def test_router_level_declaration_covers_its_routes() -> None:
    app = FastAPI()
    router = APIRouter(dependencies=[Depends(require(P.USER_READ))])

    @router.get("/users")
    async def users() -> list[str]:
        return []

    @app.get("/ping", dependencies=[PUBLIC])
    async def ping() -> None:
        pass

    app.include_router(router)
    assert access_table(app) == {"GET /users": "user:read", "GET /ping": "public"}


def test_an_app_with_no_api_routes_is_an_error() -> None:
    # Guards against the check silently finding nothing (as happened when FastAPI changed how
    # included routers are stored).
    with pytest.raises(RuntimeError, match="No API routes found"):
        access_table(FastAPI())


# ----------------------------------------------------------------------------- require() at runtime


@pytest.fixture
def client() -> TestClient:
    app = create_app(Settings(environment="test", jwt_secret=SECRET))  # type: ignore[arg-type]

    @app.get("/api/v1/_test/admin-only", dependencies=[Depends(require(P.USER_WRITE))])
    async def admin_only() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(app)


def bearer(role: str) -> dict[str, str]:
    token = create_access_token(Principal(uuid.uuid4(), uuid.uuid4(), role), SECRET, 15)
    return {"Authorization": f"Bearer {token}"}


def test_role_with_the_permission_passes(client: TestClient) -> None:
    assert client.get("/api/v1/_test/admin-only", headers=bearer("ADMIN")).status_code == 200


@pytest.mark.parametrize("role", ["TEACHER", "STUDENT", "SUPERUSER"])
def test_role_without_the_permission_is_forbidden(client: TestClient, role: str) -> None:
    response = client.get("/api/v1/_test/admin-only", headers=bearer(role))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_no_token_is_unauthenticated_not_forbidden(client: TestClient) -> None:
    response = client.get("/api/v1/_test/admin-only")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# ----------------------------------------------------------------------------- the role table


@pytest.mark.parametrize(
    "permission",
    [
        P.QUESTION_READ,
        P.TEST_CASE_READ_HIDDEN,
        P.ATTEMPT_READ,
        P.SUBMISSION_READ_FULL,
        P.GRADING_WRITE,
        P.PROCTORING_EVENT_READ,
        P.EVIDENCE_READ,
    ],
)
def test_admin_is_kept_out_of_academic_content(permission: Permission) -> None:
    assert not role_has("ADMIN", permission)


@pytest.mark.parametrize(
    "permission",
    [
        P.QUESTION_READ,
        P.TEST_CASE_READ_HIDDEN,
        P.SUBMISSION_READ_FULL,
        P.PROCTORING_EVENT_READ,
        P.EVIDENCE_READ,
        P.PROCTORING_EVENT_REVIEW,
        P.USER_WRITE,
        P.EXAM_WRITE,
        P.RESULT_RELEASE,
    ],
)
def test_student_cannot(permission: Permission) -> None:
    assert not role_has("STUDENT", permission)


def test_teacher_cannot_manage_accounts() -> None:
    assert not role_has("TEACHER", P.USER_WRITE)
    assert not role_has("TEACHER", P.AUDIT_LOG_READ)


def test_everyone_can_reach_their_own_account() -> None:
    for role in ("ADMIN", "TEACHER", "STUDENT"):
        assert role_has(role, P.ACCOUNT_SELF)


def test_unknown_role_has_nothing() -> None:
    assert not any(role_has("SUPERUSER", permission) for permission in Permission)


def test_every_permission_is_granted_to_some_role() -> None:
    granted = set().union(*ROLE_PERMISSIONS.values())
    assert granted == set(Permission)  # no dead permission names
