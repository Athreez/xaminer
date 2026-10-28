"""The question bank through the real HTTP API (PRD QB-01, QB-07, QB-09)."""

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.models import AuditLog
from app.auth.tokens import Principal, create_access_token
from app.db.session import SessionFactory, create_session_factory, tenant_session
from app.main import create_app
from app.platform.models import Institution
from app.questions.models import QuestionOption, QuestionVersion
from app.questions.service import title_of
from app.users.models import User
from cli import commands
from tests.db.api_helpers import SECRET, make_settings
from tests.db.question_helpers import purge_institutions

URL = "/api/v1/questions"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@dataclass
class World:
    factory: SessionFactory
    college: Institution
    ids: list[uuid.UUID]

    async def user(
        self, role: str = "TEACHER", college: Institution | None = None
    ) -> dict[str, str]:
        college = college or self.college
        async with tenant_session(self.factory, college.id) as s:
            user = User(email=f"u{uuid.uuid4().hex[:8]}@abc.edu", full_name=f"{role} X", role=role)
            s.add(user)
            await s.commit()
        principal = Principal(user.id, college.id, role)
        return {"Authorization": f"Bearer {create_access_token(principal, SECRET, 15)}"}

    async def other_college(self) -> Institution:
        college = await commands.create_institution(
            self.factory, f"Questions API test {uuid.uuid4().hex[:8]}"
        )
        self.ids.append(college.id)
        return college

    async def lock(self, version_id: str) -> None:
        async with tenant_session(self.factory, self.college.id) as s:
            await s.execute(
                update(QuestionVersion)
                .where(QuestionVersion.id == uuid.UUID(version_id))
                .values(is_locked=True)
            )
            await s.commit()

    async def audit(self, action: str) -> list[AuditLog]:
        async with tenant_session(self.factory, self.college.id) as s:
            return list(await s.scalars(select(AuditLog).where(AuditLog.action == action)))


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(
        factory, f"Questions API test {uuid.uuid4().hex[:8]}"
    )
    w = World(factory, college, [college.id])
    yield w
    await purge_institutions(migrator_engine, w.ids)


def mcq(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "MCQ",
        "body": "## Arrays\nWhat is the index of the **first** element?",
        "points": "2",
        "tags": ["Arrays", "easy", "arrays"],
        "options": [
            {"label": "0", "is_correct": True},
            {"label": "1", "is_correct": False},
        ],
    }
    return body | overrides


def create(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    response = client.post(URL, json=mcq(**overrides), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


# ----------------------------------------------------------------------------- access


async def test_only_teachers(client: TestClient, world: World) -> None:
    for role in ("ADMIN", "STUDENT"):
        headers = await world.user(role)
        assert client.get(URL, headers=headers).status_code == 403
        assert client.post(URL, json=mcq(), headers=headers).status_code == 403


# ----------------------------------------------------------------------------- create and read


async def test_create_and_read(client: TestClient, world: World) -> None:
    me = await world.user()
    created = create(client, me)
    assert created["tags"] == ["arrays", "easy"]  # lower-cased, repeats dropped
    assert created["visibility"] == "PRIVATE" and created["is_mine"] is True
    version = created["version"]
    assert version["version_no"] == 1 and version["points"] == "2.00"
    assert [(o["label"], o["is_correct"]) for o in version["options"]] == [
        ("0", True),
        ("1", False),
    ]
    again = client.get(f"{URL}/{created['id']}", headers=me).json()
    assert again == created
    assert len(await world.audit("question.created")) == 1


async def test_rejects_bad_input(client: TestClient, world: World) -> None:
    me = await world.user()
    for bad in (
        {"type": "ESSAY"},
        {"points": "0"},
        {"points": "1.234"},
        {"body": "   "},
        {"tags": ["x" * 51]},
        {"options": [{"label": str(i), "is_correct": False} for i in range(11)]},
        {"owner_id": str(uuid.uuid4())},
    ):
        assert client.post(URL, json=mcq(**bad), headers=me).status_code == 422, bad


# ----------------------------------------------------------------------------- list and search


async def test_list_who_sees_what(client: TestClient, world: World) -> None:
    me, colleague = await world.user(), await world.user()
    outsider = await world.user(college=await world.other_college())
    mine = create(client, me)
    shared = create(client, colleague, visibility="INSTITUTION", body="Shared question")
    create(client, colleague, body="Colleague's private question")
    create(client, outsider, visibility="INSTITUTION", body="Other college")

    def ids(**params: str) -> list[str]:
        response = client.get(URL, params=params, headers=me)
        assert response.status_code == 200, response.text
        return [q["id"] for q in response.json()["data"]]

    assert ids() == [shared["id"], mine["id"]]
    assert ids(owner="mine") == [mine["id"]]
    assert ids(owner="shared") == [shared["id"]]
    listed = client.get(URL, headers=me).json()["data"]
    assert listed[1]["title"] == "Arrays" and listed[0]["is_mine"] is False


async def test_search_and_filters(client: TestClient, world: World) -> None:
    me = await world.user()
    linked = create(client, me, body="Reverse a linked list in place", tags=["lists"])
    tree = create(client, me, type="DESCRIPTIVE", body="Explain binary search trees", options=[])

    def ids(**params: str) -> list[str]:
        return [q["id"] for q in client.get(URL, params=params, headers=me).json()["data"]]

    assert ids(q="linked list") == [linked["id"]]  # whole words
    assert ids(q="revers") == [linked["id"]]  # part of a word
    assert ids(q="lists") == [linked["id"]]  # tags
    assert ids(q="%") == []
    assert ids(type="DESCRIPTIVE") == [tree["id"]]
    assert ids(tag="LISTS") == [linked["id"]]
    assert ids(tag="nothing") == []


async def test_pages(client: TestClient, world: World) -> None:
    me = await world.user()
    made = [create(client, me, body=f"Question {i}")["id"] for i in range(5)]
    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": "2", **({"cursor": cursor} if cursor else {})}
        page = client.get(URL, params=params, headers=me).json()
        seen += [q["id"] for q in page["data"]]
        if not (cursor := page["next_cursor"]):
            break
    assert seen == list(reversed(made))


# ----------------------------------------------------------------------------- edit and versions


async def test_edit_unlocked_changes_version_in_place(client: TestClient, world: World) -> None:
    me = await world.user()
    q = create(client, me)
    url = f"{URL}/{q['id']}"
    changed = client.patch(
        url,
        json={
            "body": "New text",
            "options": [{"label": "A", "is_correct": True}, {"label": "B", "is_correct": False}],
        },
        headers=me,
    )
    assert changed.status_code == 200 and "X-New-Version" not in changed.headers
    version = changed.json()["version"]
    assert version["version_no"] == 1 and version["id"] == q["version"]["id"]
    assert version["body"] == "New text" and [o["label"] for o in version["options"]] == ["A", "B"]
    (row,) = await world.audit("question.updated")
    assert row.changes is not None and row.changes["body"]["new"] == "New text"

    same = client.patch(url, json={"body": "New text"}, headers=me)
    assert same.status_code == 200
    assert len(await world.audit("question.updated")) == 1  # nothing changed: no entry


async def test_edit_locked_makes_a_new_version(client: TestClient, world: World) -> None:
    me = await world.user()
    q = create(client, me)
    url = f"{URL}/{q['id']}"
    await world.lock(q["version"]["id"])

    tags_only = client.patch(
        url, json={"tags": ["recursion"], "visibility": "INSTITUTION"}, headers=me
    )
    assert tags_only.status_code == 200 and "X-New-Version" not in tags_only.headers
    assert tags_only.json()["version"]["version_no"] == 1  # not content: same version

    edited = client.patch(url, json={"points": "3"}, headers=me)
    assert edited.status_code == 200 and edited.headers["X-New-Version"] == "true"
    v2 = edited.json()["version"]
    assert v2["version_no"] == 2 and v2["points"] == "3.00" and not v2["is_locked"]
    assert v2["body"] == q["version"]["body"]  # everything else carried over
    assert [o["label"] for o in v2["options"]] == ["0", "1"]

    async with tenant_session(world.factory, world.college.id) as s:  # version 1 untouched
        v1 = await s.get(QuestionVersion, uuid.UUID(q["version"]["id"]))
        assert v1 is not None and str(v1.points) == "2.00" and v1.is_locked
        options = await s.scalars(select(QuestionOption).where(QuestionOption.version_id == v1.id))
        assert len(list(options)) == 2

    again = client.patch(url, json={"points": "4"}, headers=me)  # v2 is unlocked: in place
    assert again.json()["version"]["version_no"] == 2 and "X-New-Version" not in again.headers


async def test_clearing_optional_fields(client: TestClient, world: World) -> None:
    me = await world.user()
    q = create(
        client, me, type="DESCRIPTIVE", options=[], rubric="Mention O(log n)", max_answer_length=500
    )
    cleared = client.patch(
        f"{URL}/{q['id']}", json={"rubric": None, "max_answer_length": None}, headers=me
    ).json()["version"]
    assert cleared["rubric"] is None and cleared["max_answer_length"] is None


# ----------------------------------------------------------------------- sharing, copy, archive


async def test_shared_questions_can_be_read_and_copied_not_changed(
    client: TestClient, world: World
) -> None:
    owner, colleague = await world.user(), await world.user()
    q = create(client, owner, visibility="INSTITUTION")
    url = f"{URL}/{q['id']}"
    assert client.get(url, headers=colleague).json()["is_mine"] is False
    for method, path, body in (
        ("PATCH", url, {"body": "mine now"}),
        ("POST", f"{url}/archive", None),
        ("POST", f"{url}/restore", None),
    ):
        response = client.request(method, path, json=body, headers=colleague)
        assert response.status_code == 403 and response.json()["error"]["code"] == "NOT_OWNER"

    copy = client.post(f"{url}/copy", headers=colleague)
    assert copy.status_code == 201
    copied = copy.json()
    assert copied["id"] != q["id"] and copied["is_mine"] is True
    assert copied["visibility"] == "PRIVATE" and copied["version"]["version_no"] == 1
    assert copied["version"]["body"] == q["version"]["body"]
    assert [o["label"] for o in copied["version"]["options"]] == ["0", "1"]
    (row,) = await world.audit("question.copied")
    assert row.changes == {"from_question": q["id"], "from_version": 1}


async def test_sharing_rules(client: TestClient, world: World) -> None:
    """ACC-04: Private is owner only; Institution is view and copy for colleagues, never edit."""
    owner, colleague = await world.user(), await world.user()
    outsider = await world.user(college=await world.other_college())
    q = create(client, owner, visibility="INSTITUTION")
    url = f"{URL}/{q['id']}"

    # Shared: the colleague sees the full question, answer key included (they may use it).
    seen = client.get(url, headers=colleague).json()
    assert seen["version"]["options"][0]["is_correct"] is True
    # Another college never sees it, shared or not.
    assert client.get(url, headers=outsider).status_code == 404
    assert client.post(f"{url}/copy", headers=outsider).status_code == 404
    assert client.get(URL, headers=outsider).json()["data"] == []

    # A copy is independent: editing it leaves the original alone, and the other way round.
    copy = client.post(f"{url}/copy", headers=colleague).json()
    client.patch(f"{URL}/{copy['id']}", json={"body": "Colleague's wording"}, headers=colleague)
    client.patch(url, json={"body": "Owner's wording"}, headers=owner)
    assert client.get(url, headers=owner).json()["version"]["body"] == "Owner's wording"
    assert (
        client.get(f"{URL}/{copy['id']}", headers=colleague).json()["version"]["body"]
        == "Colleague's wording"
    )
    # The copy is private to the colleague.
    assert client.get(f"{URL}/{copy['id']}", headers=owner).status_code == 404

    # Making it private again hides it from the colleague at once.
    client.patch(url, json={"visibility": "PRIVATE"}, headers=owner)
    assert client.get(url, headers=colleague).status_code == 404
    assert client.post(f"{url}/copy", headers=colleague).status_code == 404
    assert q["id"] not in [x["id"] for x in client.get(URL, headers=colleague).json()["data"]]


async def test_archived_shared_questions_leave_colleagues_lists(
    client: TestClient, world: World
) -> None:
    owner, colleague = await world.user(), await world.user()
    q = create(client, owner, visibility="INSTITUTION")
    client.post(f"{URL}/{q['id']}/archive", headers=owner)

    def ids(headers: dict[str, str], **params: str) -> list[str]:
        return [x["id"] for x in client.get(URL, params=params, headers=headers).json()["data"]]

    assert ids(colleague) == [] and ids(colleague, archived="true") == []
    assert ids(owner, archived="true") == [q["id"]]
    # Still readable by id: exams that use it must keep working.
    assert client.get(f"{URL}/{q['id']}", headers=colleague).status_code == 200


async def test_archive_and_restore(client: TestClient, world: World) -> None:
    me = await world.user()
    q = create(client, me)
    url = f"{URL}/{q['id']}"
    archived = client.post(f"{url}/archive", headers=me).json()
    assert archived["archived_at"] is not None
    assert client.get(URL, headers=me).json()["data"] == []
    assert [
        x["id"] for x in client.get(URL, params={"archived": "true"}, headers=me).json()["data"]
    ] == [q["id"]]
    assert client.get(url, headers=me).status_code == 200  # still readable
    restored = client.post(f"{url}/restore", headers=me).json()
    assert restored["archived_at"] is None
    assert len(await world.audit("question.archived")) == 1
    assert len(await world.audit("question.restored")) == 1


def test_title_of() -> None:
    assert title_of("## Arrays\nmore") == "Arrays"
    assert title_of("\n\n  **Bold** and `code` [link](http://x)") == "Bold and code link"
    assert title_of("x" * 200).endswith("…") and len(title_of("x" * 200)) == 120


# ------------------------------------------------------------------------ type rules (QB-02..05)

TF = [{"label": "true", "is_correct": False}, {"label": "FALSE", "is_correct": True}]


def opts(*correct: bool) -> list[dict[str, Any]]:
    return [{"label": f"Option {i}", "is_correct": c} for i, c in enumerate(correct)]


@pytest.mark.parametrize(
    ("body", "field", "message"),
    [
        ({"options": opts(True)}, "options", "between 2 and 10"),
        ({"options": opts(True, True)}, "options", "exactly one"),
        ({"options": opts(False, False)}, "options", "exactly one"),
        (
            {
                "options": [
                    {"label": "Yes", "is_correct": True},
                    {"label": " yes ", "is_correct": False},
                ]
            },
            "options.1.label",
            "same as option 1",
        ),
        ({"msq_scoring": "PARTIAL"}, "msq_scoring", "Only multiple-select"),
        ({"rubric": "Look for X"}, "rubric", "Only descriptive"),
        ({"max_answer_length": 100}, "max_answer_length", "Only descriptive"),
        (
            {"points": "1", "negative_marks": "2"},
            "negative_marks",
            "more than the question's points",
        ),
        ({"type": "MSQ", "options": opts(False, False)}, "options", "at least one"),
        ({"type": "TRUE_FALSE", "options": opts(True, False)}, "options", '"True", then "False"'),
        (
            {"type": "TRUE_FALSE", "options": [*TF[:1], {"label": "false", "is_correct": False}]},
            "options",
            "either True or False",
        ),
        ({"type": "DESCRIPTIVE"}, "options", "has no options"),
        ({"type": "CODING"}, "options", "has no options"),
    ],
    ids=[
        "mcq-one-option",
        "mcq-two-correct",
        "mcq-none-correct",
        "duplicate-labels",
        "mcq-scoring",
        "mcq-rubric",
        "mcq-max-length",
        "negative-over-points",
        "msq-none-correct",
        "tf-wrong-labels",
        "tf-none-correct",
        "descriptive-options",
        "coding-options",
    ],
)
async def test_type_rules(
    client: TestClient, world: World, body: dict[str, Any], field: str, message: str
) -> None:
    response = client.post(URL, json=mcq(**body), headers=await world.user())
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_FAILED"
    assert any(d["field"] == field and message in d["message"] for d in error["details"]), error


async def test_valid_shapes(client: TestClient, world: World) -> None:
    me = await world.user()
    msq = create(client, me, type="MSQ", options=opts(True, True, False))
    assert msq["version"]["msq_scoring"] == "ALL_OR_NOTHING"  # the default
    partial = create(client, me, type="MSQ", options=opts(True, False), msq_scoring="PARTIAL")
    assert partial["version"]["msq_scoring"] == "PARTIAL"
    tf = create(client, me, type="TRUE_FALSE", options=TF)
    assert [(o["label"], o["is_correct"]) for o in tf["version"]["options"]] == [
        ("True", False),
        ("False", True),
    ]  # fixed spelling
    essay = create(
        client, me, type="DESCRIPTIVE", options=[], rubric="Key points", max_answer_length=800
    )
    assert essay["version"]["rubric"] == "Key points"
    create(client, me, type="CODING", options=[])
    create(client, me, options=opts(*([False] * 9), True))  # 10 options


async def test_edits_are_checked_too(client: TestClient, world: World) -> None:
    me = await world.user()
    q = create(client, me, type="MSQ", options=opts(True, False), msq_scoring="PARTIAL")
    url = f"{URL}/{q['id']}"
    none_correct = client.patch(url, json={"options": opts(False, False)}, headers=me)
    assert none_correct.status_code == 422
    over = client.patch(url, json={"negative_marks": "5"}, headers=me)  # points are 2
    assert over.status_code == 422
    # Clearing the scoring mode falls back to the default instead of leaving it empty.
    reset = client.patch(url, json={"msq_scoring": None}, headers=me).json()
    assert reset["version"]["msq_scoring"] == "ALL_OR_NOTHING"
    (row,) = await world.audit("question.updated")
    assert row.changes == {"msq_scoring": {"old": "PARTIAL", "new": "ALL_OR_NOTHING"}}


# ---------------------------------------------------------------------- Markdown is cleaned (QB-06)


async def test_markdown_is_sanitised_on_save(client: TestClient, world: World) -> None:
    me = await world.user()
    q = create(
        client,
        me,
        body="Pick one <img src=x onerror=alert(1)>[docs](javascript:alert(1))"
        "\n\n```\n<b>code</b>\n```",
        options=[
            {"label": "<script>alert(1)</script>Yes", "is_correct": True},
            {"label": "No", "is_correct": False},
        ],
    )
    version = q["version"]
    assert version["body"] == "Pick one [docs](#)\n\n```\n<b>code</b>\n```"  # code kept as typed
    assert version["options"][0]["label"] == "Yes"
    essay = create(client, me, type="DESCRIPTIVE", options=[], rubric="<iframe src=x></iframe>")
    assert essay["version"]["rubric"] is None  # nothing left of it

    only_html = client.post(URL, json=mcq(body="<script>alert(1)</script>"), headers=me)
    assert only_html.status_code == 422
    assert only_html.json()["error"]["details"][0]["field"] == "body"
    empty_option = mcq(
        options=[{"label": "<b></b>", "is_correct": True}, {"label": "B", "is_correct": False}]
    )
    response = client.post(URL, json=empty_option, headers=me)
    assert response.status_code == 422
    assert any(d["field"] == "options.0.label" for d in response.json()["error"]["details"])
