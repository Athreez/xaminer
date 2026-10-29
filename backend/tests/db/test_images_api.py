"""Image upload through the real API and real storage (PRD QB-06)."""

import io
import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.models import AuditLog
from app.auth.tokens import Principal, create_access_token
from app.db.session import SessionFactory, create_session_factory, tenant_session
from app.main import create_app
from app.platform.models import Institution
from app.users.models import User
from cli import commands
from tests.db.api_helpers import S3_PORT, SECRET, make_settings
from tests.db.question_helpers import purge_institutions
from tests.services import require

URL = "/api/v1/uploads/images"


@pytest.fixture(autouse=True)
def storage_running() -> None:
    require(S3_PORT, "Object storage")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def factory(app_engine: AsyncEngine) -> SessionFactory:
    return create_session_factory(app_engine)


@pytest.fixture
async def colleges(
    factory: SessionFactory, migrator_engine: AsyncEngine
) -> AsyncIterator[list[Institution]]:
    made: list[Institution] = []
    yield made
    await purge_institutions(migrator_engine, [c.id for c in made])


async def member(factory: SessionFactory, colleges: list[Institution], role: str) -> dict[str, str]:
    college = await commands.create_institution(factory, f"Images test {uuid.uuid4().hex[:8]}")
    colleges.append(college)
    async with tenant_session(factory, college.id) as s:
        user = User(email=f"u{uuid.uuid4().hex[:8]}@abc.edu", full_name="T", role=role)
        s.add(user)
        await s.commit()
    return {
        "Authorization": "Bearer "
        + create_access_token(Principal(user.id, college.id, role), SECRET, 15)
    }


def png(width: int = 40, height: int = 30) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "orange").save(out, "PNG")
    return out.getvalue()


def upload(client: TestClient, headers: dict[str, str], data: bytes, name: str = "a.png"):  # type: ignore[no-untyped-def]
    return client.post(URL, files={"file": (name, data, "image/png")}, headers=headers)


async def test_upload_store_and_fetch(
    client: TestClient, factory: SessionFactory, colleges: list[Institution]
) -> None:
    teacher = await member(factory, colleges, "TEACHER")
    response = upload(client, teacher, png())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["ref"] == f"/api/v1/images/{body['id']}"
    assert (body["width"], body["height"]) == (40, 30)

    fetched = httpx.get(body["url"])
    assert fetched.status_code == 200 and fetched.headers["content-type"] == "image/webp"
    assert Image.open(io.BytesIO(fetched.content)).size == (40, 30)

    # The link can't be altered, and the object can't be read without one.
    assert (
        httpx.get(body["url"].replace("X-Amz-Signature=", "X-Amz-Signature=0")).status_code == 403
    )
    assert httpx.get(body["url"].split("?")[0]).status_code == 403

    async with tenant_session(factory, colleges[0].id) as s:
        (row,) = await s.scalars(select(AuditLog).where(AuditLog.action == "image.uploaded"))
        assert str(row.target_id) == body["id"]


async def test_question_text_gets_signed_links(
    client: TestClient, factory: SessionFactory, colleges: list[Institution]
) -> None:
    teacher = await member(factory, colleges, "TEACHER")
    ref = upload(client, teacher, png()).json()["ref"]
    question = client.post(
        "/api/v1/questions",
        json={"type": "DESCRIPTIVE", "points": "1", "body": f"Read the chart:\n\n![chart]({ref})"},
        headers=teacher,
    ).json()
    body = question["version"]["body"]
    assert ref not in body and "X-Amz-Signature" in body
    link = body.split("](")[1].rstrip(")")
    assert httpx.get(link).status_code == 200


async def test_another_colleges_image_cannot_be_borrowed(
    client: TestClient, factory: SessionFactory, colleges: list[Institution]
) -> None:
    owner = await member(factory, colleges, "TEACHER")
    stranger = await member(factory, colleges, "TEACHER")
    ref = upload(client, owner, png()).json()["ref"]
    question = client.post(
        "/api/v1/questions",
        json={"type": "DESCRIPTIVE", "points": "1", "body": f"![x]({ref})"},
        headers=stranger,
    ).json()
    link = question["version"]["body"].split("](")[1].rstrip(")")
    assert httpx.get(link).status_code == 404  # signed for the stranger's college: no such image


async def test_bad_uploads_are_refused(
    client: TestClient, factory: SessionFactory, colleges: list[Institution]
) -> None:
    teacher = await member(factory, colleges, "TEACHER")
    fake = upload(client, teacher, b"<?php system($_GET['c']); ?>", name="shell.png")
    assert fake.status_code == 422 and fake.json()["error"]["code"] == "INVALID_IMAGE"
    assert upload(client, teacher, png() + b"\0" * (2 * 1024 * 1024)).status_code == 422
    assert client.post(URL, headers=teacher).status_code == 422  # no file


async def test_only_teachers_upload(
    client: TestClient, factory: SessionFactory, colleges: list[Institution]
) -> None:
    for role in ("ADMIN", "STUDENT"):
        assert upload(client, await member(factory, colleges, role), png()).status_code == 403
    assert client.post(URL, files={"file": ("a.png", png(), "image/png")}).status_code == 401
