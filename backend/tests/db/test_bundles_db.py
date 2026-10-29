"""Building test bundles into object storage (TCK-0704): rebuilt on change, hash in the key."""

import io
import tarfile
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import boto3
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.storage import Storage
from app.db.session import create_session_factory, tenant_session
from app.main import create_app
from app.questions import bundles
from app.questions.models import CodingConfig, QuestionVersion
from cli import commands
from tests.db.api_helpers import S3_PORT, make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_questions_api import URL, World
from tests.services import ENV, require


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    require(S3_PORT, "Object storage")
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(factory, f"Bundle test {uuid.uuid4().hex[:8]}")
    w = World(factory, college, [college.id])
    yield w
    await purge_institutions(migrator_engine, w.ids)


def download(key: str) -> dict[str, bytes]:
    settings = make_settings()
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=ENV.get("S3_SECRET_KEY", ""),
        region_name="us-east-1",
    )
    data = s3.get_object(Bucket=bundles.BUNDLES, Key=key)["Body"].read()
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers()}  # type: ignore[union-attr]


async def test_bundle_built_stored_and_rebuilt_on_change(
    client: TestClient, world: World, no_bundle_jobs: list[uuid.UUID]
) -> None:
    me = await world.user()
    question: dict[str, Any] = client.post(
        URL, json={"type": "CODING", "body": "Add.", "points": "5"}, headers=me
    ).json()
    qid, version_id = question["id"], uuid.UUID(question["version"]["id"])
    q = f"{URL}/{qid}"
    client.put(
        f"{q}/coding", json={"allowed_languages": [{"language_key": "python312"}]}, headers=me
    )
    client.post(
        f"{q}/test-cases",
        json={"visibility": "PUBLIC", "input": "1 2", "expected_output": "3"},
        headers=me,
    )
    case = client.post(
        f"{q}/test-cases", json={"input": "5 7", "expected_output": "12"}, headers=me
    ).json()
    assert no_bundle_jobs == [version_id, version_id]  # a rebuild is queued after each change

    storage = Storage(make_settings())

    async def build() -> str | None:
        return await bundles.build(world.factory, storage, version_id)

    async def saved_key() -> str | None:
        async with tenant_session(world.factory, world.college.id) as s:
            return await s.scalar(
                select(CodingConfig.bundle_key).where(CodingConfig.version_id == version_id)
            )

    key = await build()
    assert key is not None and key.startswith(f"{world.college.id}/") and key.endswith(".tar")
    assert await saved_key() == key
    files = download(key)
    assert files["001.in"] == b"1 2" and files["002.out"] == b"12"
    assert await build() == key  # nothing changed: same bundle

    client.patch(f"{q}/test-cases/{case['id']}", json={"expected_output": "13"}, headers=me)
    assert await saved_key() is None  # stale until rebuilt
    assert no_bundle_jobs[-1] == version_id
    rebuilt = await build()
    assert rebuilt != key and download(rebuilt)["002.out"] == b"13"  # type: ignore[arg-type]

    # A copy has the same test cases, so it shares the bundle.
    copy = client.post(f"{q}/copy", headers=me).json()
    async with tenant_session(world.factory, world.college.id) as s:
        copied = await s.scalar(
            select(CodingConfig.bundle_key).where(
                CodingConfig.version_id == uuid.UUID(copy["version"]["id"])
            )
        )
        await s.execute(
            update(QuestionVersion).where(QuestionVersion.id == version_id).values(is_locked=True)
        )
        await s.commit()
    assert copied == rebuilt
    assert await build() == rebuilt  # locked: left as it is, no error


async def test_missing_version_is_ignored(world: World) -> None:
    assert await bundles.build(world.factory, Storage(make_settings()), uuid.uuid4()) is None
