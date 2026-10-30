"""Accessibility (NFR-11; TCK-1405): no serious or critical axe (WCAG 2.1 AA) problems on the main
pages of every role, in light and dark mode; and a student takes a whole exam with the keyboard."""

import re

import pytest
from playwright.sync_api import Browser, Page, expect

from conftest import ADMIN, BASE, TEACHER, Api, axe_problems, login

STUDENT = "student09@demo.test"


def check(page: Page, path: str, ready: str, problems: dict[str, list[str]]) -> None:
    page.goto(BASE + path)
    expect(page.get_by_text(ready).first).to_be_visible()
    page.wait_for_load_state("networkidle")
    found = axe_problems(page)
    if found:
        problems[path] = found


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_main_pages_have_no_serious_problems(
    browser: Browser, teacher: Api, make_exam, scheme: str
) -> None:  # type: ignore[no-untyped-def]
    exam = make_exam(STUDENT, ["demo-stack", "demo-recursion"])
    question = teacher("GET", "/questions", params={"tag": "demo-stack", "owner": "mine"})["data"][0]["id"]
    problems: dict[str, list[str]] = {}
    context = browser.new_context(viewport={"width": 1366, "height": 900}, color_scheme=scheme)
    page = context.new_page()
    try:
        page.goto(f"{BASE}/login")
        found = axe_problems(page)
        if found:
            problems["/login"] = found

        login(page, ADMIN)
        for path, ready in [
            ("/admin/users", "Users"),
            ("/admin/groups", "Groups"),
            ("/admin/settings", "Default consent text"),
            ("/admin/audit", "Audit log"),
        ]:
            check(page, path, ready, problems)

        context.clear_cookies()
        login(page, TEACHER)
        for path, ready in [
            ("/teacher", "Answers to mark"),
            ("/teacher/questions", "Questions"),
            (f"/teacher/questions/{question}", "Which data structure"),
            ("/teacher/exams", "Exams"),
            (f"/teacher/exams/{exam}", "Overview"),
            (f"/teacher/exams/{exam}/questions", "Which data structure"),
            (f"/teacher/exams/{exam}/settings", "Schedule"),
            (f"/teacher/exams/{exam}/students", "assigned"),
            (f"/teacher/exams/{exam}/monitor", "Refreshes every 10 s"),
            (f"/teacher/exams/{exam}/results", "Release results"),
        ]:
            check(page, path, ready, problems)

        context.clear_cookies()
        login(page, STUDENT)
        for path, ready in [
            ("/student", "Your exams"),
            (f"/student/exams/{exam}", "Start"),
            ("/student/results", "Results"),
            ("/student/notifications", "Notifications"),
        ]:
            check(page, path, ready, problems)
        page.goto(f"{BASE}/student/exams/{exam}")
        page.get_by_role("button", name=re.compile("^Start")).click()
        page.get_by_role("dialog").get_by_role("button", name="Start").click()
        expect(page.get_by_text("Which data structure")).to_be_visible()
        page.wait_for_load_state("networkidle")
        found = axe_problems(page)
        if found:
            problems["exam screen"] = found
    finally:
        context.close()
    report = "\n".join(f"{where}:\n  " + "\n  ".join(items) for where, items in problems.items())
    assert not problems, f"axe ({scheme}):\n{report}"


def tab_to(page: Page, role: str, name: str | re.Pattern[str], limit: int = 80) -> None:
    """Press Tab until the focused element is this one (fails if Tab never gets there)."""
    target = page.get_by_role(role, name=name).first  # type: ignore[arg-type]
    for _ in range(limit):
        page.keyboard.press("Tab")
        if target.evaluate("el => el === document.activeElement"):
            return
    raise AssertionError(f"Tab never reached {role} {name!r}")


def choose(page: Page, label: str) -> None:
    """Tab into the radio group, then arrow keys to the option (the standard radio pattern)."""
    for _ in range(80):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement?.type === 'radio'"):
            break
    target = page.get_by_role("radio", name=label)
    for _ in range(10):
        if target.evaluate("el => el === document.activeElement"):
            page.keyboard.press("Space")
            return
        page.keyboard.press("ArrowDown")
    raise AssertionError(f"arrow keys never reached {label!r}")


def test_a_whole_exam_with_the_keyboard_only(page: Page, make_exam) -> None:  # type: ignore[no-untyped-def]
    student = "student08@demo.test"
    exam = make_exam(student, ["demo-stack", "demo-hash-lookup", "demo-recursion"])
    login(page, student)
    page.goto(f"{BASE}/student/exams/{exam}")
    expect(page.get_by_role("button", name=re.compile("^Start"))).to_be_visible()

    tab_to(page, "button", re.compile("^Start"))
    page.keyboard.press("Enter")
    expect(page.get_by_role("dialog")).to_be_visible()
    tab_to(page, "button", "Start")
    page.keyboard.press("Enter")

    expect(page.get_by_text("Which data structure")).to_be_visible()
    choose(page, "Stack")
    expect(page.get_by_role("radio", name="Stack")).to_be_checked()
    tab_to(page, "button", re.compile("^Next"))
    page.keyboard.press("Enter")

    expect(page.get_by_text("Looking up a key in a hash table")).to_be_visible()
    choose(page, "True")
    expect(page.get_by_role("radio", name="True")).to_be_checked()
    tab_to(page, "button", re.compile("^Next"))
    page.keyboard.press("Enter")

    expect(page.get_by_text("Explain recursion")).to_be_visible()
    tab_to(page, "textbox", re.compile("answer", re.I))
    page.keyboard.type("A function that calls itself; the base case stops it.")

    tab_to(page, "button", re.compile("Review & submit"))
    page.keyboard.press("Enter")
    tab_to(page, "button", re.compile("^Submit"))
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    tab_to(page, "button", re.compile("^Submit"))
    page.keyboard.press("Enter")
    expect(page.get_by_text(re.compile("receipt", re.I)).first).to_be_visible()
