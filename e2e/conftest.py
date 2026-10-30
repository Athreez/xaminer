"""Browser tests against a running stack with the demo data (TCK-1402, TCK-1405).

    make e2e            (the stack up, runners built, `make demo-data` done)

E2E_BASE (default http://localhost:8080) and XAMINER_DEMO_PASSWORD (the demo accounts') say
where and how to log in. E2E_CHANNEL=msedge uses an installed Edge instead of Playwright's
Chromium. Every test makes its own exam through the API, so the tests can run again and again.
"""

import os
import re
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import requests
from playwright.sync_api import Browser, Page, expect, sync_playwright

BASE = os.environ.get("E2E_BASE", "http://localhost:8080").rstrip("/")
API = f"{BASE}/api/v1"
PASSWORD = os.environ.get("XAMINER_DEMO_PASSWORD", "Demo-Xaminer-2026")
TEACHER = "teacher@demo.test"
ADMIN = "admin@demo.test"
AXE = Path(__file__).resolve().parent.parent / "frontend" / "node_modules" / "axe-core" / "axe.min.js"

expect.set_options(timeout=15_000)


class Api:
    """The API as one user."""

    def __init__(self, email: str) -> None:
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD}, timeout=30)
        assert r.ok, f"login {email}: {r.text}"
        self.headers = {"Authorization": "Bearer " + r.json()["access_token"]}

    def __call__(self, method: str, path: str, **kw: Any) -> Any:
        r = requests.request(method, API + path, headers=self.headers, timeout=60, **kw)
        assert r.ok, f"{method} {path}: {r.status_code} {r.text}"
        return r.json() if r.content else None


@pytest.fixture(scope="session")
def teacher() -> Api:
    return Api(TEACHER)


def question_id(teacher: Api, tag: str) -> str:
    found = teacher("GET", "/questions", params={"tag": tag, "owner": "mine"})["data"]
    assert found, f"question tagged {tag} missing: run make demo-data"
    return found[0]["id"]  # type: ignore[no-any-return]


@pytest.fixture
def make_exam(teacher: Api) -> Callable[..., str]:
    """A published exam, open now, for one demo student; returns its id."""

    def make(student: str, tags: list[str], **settings: Any) -> str:
        now = datetime.now(UTC)
        body = {
            "title": f"E2E {uuid.uuid4().hex[:6]}",
            "open_at": (now - timedelta(minutes=5)).isoformat(),
            "close_at": (now + timedelta(hours=2)).isoformat(),
            "duration_min": 30,
            "browser_checks": False,  # test_browser_checks.py turns them on
        } | settings
        exam = teacher("POST", "/exams", json=body)["id"]
        teacher(
            "PUT",
            f"/exams/{exam}/questions",
            json={"questions": [{"question_id": question_id(teacher, t)} for t in tags]},
        )
        sid = teacher("GET", f"/exams/{exam}/student-choices", params={"q": student})[0]["id"]
        teacher("POST", f"/exams/{exam}/assignments", json={"student_ids": [sid]})
        teacher("POST", f"/exams/{exam}/publish")
        return exam  # type: ignore[no-any-return]

    return make


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        channel = os.environ.get("E2E_CHANNEL")
        b = p.chromium.launch(channel=channel) if channel else p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1366, "height": 900}, ignore_https_errors=True)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    yield page
    context.close()
    assert not errors, f"errors in the page: {errors}"


def login(page: Page, email: str) -> None:
    page.goto(f"{BASE}/login")
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Log in").click()
    page.wait_for_url(re.compile(r"/(admin|teacher|student)"))


def axe_problems(page: Page) -> list[str]:
    """Serious and critical WCAG 2.1 A/AA problems axe finds on the page as it is now."""
    page.add_script_tag(path=str(AXE))
    found = page.evaluate(
        """async () => (await axe.run(document, {runOnly: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}))
            .violations.filter(v => v.impact === 'serious' || v.impact === 'critical')
            .map(v => `${v.id} (${v.impact}): ${v.help} -> ${v.nodes.slice(0, 3).map(n => n.target.join(' ')).join(' | ')}`)"""
    )
    return list(found)
