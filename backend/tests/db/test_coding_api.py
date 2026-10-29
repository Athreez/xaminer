"""Coding questions through the real HTTP API (PRD CQ-01..09, TCK-0702)."""

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory, tenant_session
from app.main import create_app
from app.questions.models import CodingConfig
from cli import commands
from tests.db.api_helpers import make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_questions_api import URL, World


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(factory, f"Coding API test {uuid.uuid4().hex[:8]}")
    w = World(factory, college, [college.id])
    yield w
    await purge_institutions(migrator_engine, w.ids)


PY = [{"language_key": "python312", "starter_code": "a, b = map(int, input().split())\n"}]


def coding(client: TestClient, me: dict[str, str]) -> dict[str, Any]:
    response = client.post(
        URL, json={"type": "CODING", "body": "Print **a + b**.", "points": "10"}, headers=me
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def setup(client: TestClient, me: dict[str, str], qid: str, **overrides: Any) -> Any:
    return client.put(f"{URL}/{qid}/coding", json={"allowed_languages": PY} | overrides, headers=me)


def add_case(client: TestClient, me: dict[str, str], qid: str, **body: Any) -> dict[str, Any]:
    response = client.post(
        f"{URL}/{qid}/test-cases", json={"expected_output": "3"} | body, headers=me
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


async def test_new_coding_question_starts_with_defaults_and_says_what_is_missing(
    client: TestClient, world: World
) -> None:
    me = await world.user()
    created = coding(client, me)
    setup_ = created["coding"]
    assert (setup_["time_limit_ms"], setup_["memory_limit_mb"]) == (2000, 256)
    assert setup_["comparison_mode"] == "TRIM" and setup_["max_submissions"] == 10
    assert setup_["validation_status"] == "NEEDS_VALIDATION"
    assert setup_["blocks"] == [
        "Choose at least one language.",
        "Add at least one hidden test case.",
        "Add a reference solution in one of the allowed languages.",
    ]
    mcq = client.post(
        URL,
        json={
            "type": "MCQ",
            "body": "?",
            "points": "1",
            "options": [{"label": "a", "is_correct": True}, {"label": "b", "is_correct": False}],
        },
        headers=me,
    ).json()
    assert mcq["coding"] is None
    refused = client.get(f"{URL}/{mcq['id']}/test-cases", headers=me)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "NOT_CODING"

    languages = client.get("/api/v1/languages", headers=me).json()
    assert {lang["key"] for lang in languages} == {"cpp17", "java21", "python312", "node22"}


async def test_setup_is_checked(client: TestClient, world: World) -> None:
    me = await world.user()
    qid = coding(client, me)["id"]
    bad = [
        {"allowed_languages": []},
        {"allowed_languages": [{"language_key": "cobol"}]},
        {"allowed_languages": PY + PY},
        {"time_limit_ms": 50},
        {"time_limit_ms": 10_001},
        {"memory_limit_mb": 1024},
        {"comparison_mode": "FUZZY"},
        {"max_submissions": 0},
    ]
    for overrides in bad:
        assert setup(client, me, qid, **overrides).status_code == 422, overrides

    saved = setup(
        client,
        me,
        qid,
        input_format="Two integers <script>x</script>a and b",
        time_limit_ms=1500,
        comparison_mode="TOKEN",
    )
    assert saved.status_code == 200, saved.text
    got = saved.json()["coding"]
    assert got["input_format"] == "Two integers a and b"  # Markdown cleaned like question text
    assert got["allowed_languages"] == PY and got["time_limit_ms"] == 1500
    assert got["blocks"] == [
        "Add at least one hidden test case.",
        "Add a reference solution in one of the allowed languages.",
    ]
    (row,) = await world.audit("question.coding_updated")
    assert row.changes["allowed_languages"] == {"old": [], "new": ["python312"]}


async def test_test_cases_add_edit_reorder_delete(client: TestClient, world: World) -> None:
    me = await world.user()
    qid = coding(client, me)["id"]
    setup(client, me, qid)
    example = add_case(client, me, qid, visibility="PUBLIC", input="1 2")
    hidden = add_case(client, me, qid, input="5 7", expected_output="12", weight=3)
    assert hidden["visibility"] == "HIDDEN" and hidden["order_index"] == 1

    patched = client.patch(f"{URL}/{qid}/test-cases/{hidden['id']}", json={"weight": 5}, headers=me)
    assert patched.status_code == 200 and patched.json()["weight"] == 5
    bad = client.patch(f"{URL}/{qid}/test-cases/{hidden['id']}", json={"weight": 0}, headers=me)
    assert bad.status_code == 422

    order = client.put(
        f"{URL}/{qid}/test-cases/order", json={"ids": [hidden["id"], example["id"]]}, headers=me
    )
    assert [c["id"] for c in order.json()] == [hidden["id"], example["id"]]
    incomplete = client.put(
        f"{URL}/{qid}/test-cases/order", json={"ids": [hidden["id"]]}, headers=me
    )
    assert incomplete.status_code == 422

    assert client.delete(f"{URL}/{qid}/test-cases/{hidden['id']}", headers=me).status_code == 204
    listed = client.get(f"{URL}/{qid}/test-cases", headers=me).json()
    assert [(c["id"], c["order_index"]) for c in listed] == [(example["id"], 0)]  # gap closed
    other = await world.user()
    assert client.get(f"{URL}/{qid}/test-cases", headers=other).status_code == 404  # private


async def test_at_most_fifty_test_cases_of_a_megabyte(client: TestClient, world: World) -> None:
    me = await world.user()
    qid = coding(client, me)["id"]
    too_big = client.post(
        f"{URL}/{qid}/test-cases", json={"expected_output": "é" * 600_000}, headers=me
    )  # 1.2 MB once encoded
    assert too_big.status_code == 422
    for _ in range(50):
        add_case(client, me, qid)
    full = client.post(f"{URL}/{qid}/test-cases", json={"expected_output": "3"}, headers=me)
    assert full.status_code == 409 and full.json()["error"]["code"] == "TOO_MANY_TEST_CASES"


async def test_references_must_use_an_allowed_language(client: TestClient, world: World) -> None:
    me = await world.user()
    qid = coding(client, me)["id"]
    setup(client, me, qid)
    add_case(client, me, qid)
    java = client.put(
        f"{URL}/{qid}/reference-solutions/java21", json={"source": "class Main {}"}, headers=me
    )
    assert java.status_code == 422 and java.json()["error"]["code"] == "LANGUAGE_NOT_ALLOWED"
    saved = client.put(
        f"{URL}/{qid}/reference-solutions/python312", json={"source": "print(3)"}, headers=me
    ).json()["coding"]
    assert saved["reference_solutions"] == [{"language_key": "python312", "source": "print(3)"}]
    assert saved["blocks"] == []  # ready to validate

    # Switching to Java only drops the Python reference: it could no longer be run.
    after = setup(client, me, qid, allowed_languages=[{"language_key": "java21"}]).json()
    assert after["coding"]["reference_solutions"] == []
    deleted = client.delete(f"{URL}/{qid}/reference-solutions/java21", headers=me)
    assert deleted.status_code == 200


async def test_changes_that_affect_results_need_validation_again(
    client: TestClient, world: World
) -> None:
    me = await world.user()
    qid = coding(client, me)["id"]
    setup(client, me, qid)
    case = add_case(client, me, qid)

    async def mark_passed() -> None:
        async with tenant_session(world.factory, world.college.id) as s:
            await s.execute(update(CodingConfig).values(validation_status="PASSED"))
            await s.commit()

    def status() -> str:
        return client.get(f"{URL}/{qid}", headers=me).json()["coding"]["validation_status"]  # type: ignore[no-any-return]

    await mark_passed()
    setup(client, me, qid, partial_scoring=False, max_submissions=3)  # scoring only
    assert status() == "PASSED"
    for change in (
        lambda: setup(client, me, qid, time_limit_ms=3000),
        lambda: client.patch(
            f"{URL}/{qid}/test-cases/{case['id']}", json={"expected_output": "4"}, headers=me
        ),
        lambda: add_case(client, me, qid),
        lambda: client.put(
            f"{URL}/{qid}/reference-solutions/python312", json={"source": "print(4)"}, headers=me
        ),
    ):
        await mark_passed()
        change()
        assert status() == "NEEDS_VALIDATION"


async def test_a_published_version_is_never_changed_a_new_one_is_made(
    client: TestClient, world: World
) -> None:
    me = await world.user()
    created = coding(client, me)
    qid = created["id"]
    setup(client, me, qid)
    case = add_case(client, me, qid, visibility="PUBLIC", input="1 2")
    client.put(
        f"{URL}/{qid}/reference-solutions/python312", json={"source": "print(3)"}, headers=me
    )
    await world.lock(created["version"]["id"])

    # Editing a test case of the locked version edits its copy in a new version.
    patched = client.patch(
        f"{URL}/{qid}/test-cases/{case['id']}", json={"expected_output": "three"}, headers=me
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["id"] != case["id"]
    now = client.get(f"{URL}/{qid}", headers=me).json()
    assert now["version"]["version_no"] == 2 and not now["version"]["is_locked"]
    assert now["coding"]["allowed_languages"] == PY  # setup and reference came along
    assert now["coding"]["reference_solutions"][0]["source"] == "print(3)"
    assert [
        c["expected_output"] for c in client.get(f"{URL}/{qid}/test-cases", headers=me).json()
    ] == ["three"]

    # A plain question edit of a locked version carries the coding setup over too.
    await world.lock(now["version"]["id"])
    edited = client.patch(f"{URL}/{qid}", json={"body": "Print a + b, fast."}, headers=me)
    assert edited.headers.get("X-New-Version") == "true"
    assert edited.json()["coding"]["allowed_languages"] == PY

    copy = client.post(f"{URL}/{qid}/copy", headers=me).json()
    assert copy["coding"]["reference_solutions"][0]["language_key"] == "python312"
    assert copy["coding"]["validation_status"] == "NEEDS_VALIDATION"
    assert len(client.get(f"{URL}/{copy['id']}/test-cases", headers=me).json()) == 1


@pytest.mark.parametrize("role", ["ADMIN", "STUDENT"])
async def test_only_teachers_see_test_cases(client: TestClient, world: World, role: str) -> None:
    me = await world.user()
    qid = coding(client, me)["id"]
    other = await world.user(role)
    assert client.get(f"{URL}/{qid}/test-cases", headers=other).status_code == 403
    assert client.get("/api/v1/languages", headers=other).status_code == 403
