"""The main exam paths in a real browser (NFR-14; TCK-1402): an objective exam from start to
released result, a coding exam with Run and Submit, and a network cut in the middle of an exam.
(The proctored path joins with proctoring, E10.)"""

import re
import time

from playwright.sync_api import Page, expect

from conftest import BASE, TEACHER, Api, axe_problems, login


def start(page: Page, exam: str) -> None:
    page.goto(f"{BASE}/student/exams/{exam}")
    page.get_by_role("button", name=re.compile("^Start")).click()
    page.get_by_role("dialog").get_by_role("button", name="Start").click()


def submit(page: Page) -> None:
    page.get_by_role("button", name=re.compile("Review & submit")).first.click()
    page.get_by_role("button", name=re.compile("^Submit")).first.click()
    page.get_by_role("dialog").get_by_role("button", name=re.compile("^Submit")).click()
    expect(page.get_by_text(re.compile("receipt", re.I)).first).to_be_visible()


def next_question(page: Page) -> None:
    page.get_by_role("button", name=re.compile("^Next")).click()


def test_objective_exam_to_a_released_result(page: Page, make_exam, teacher: Api) -> None:  # type: ignore[no-untyped-def]
    student = "student03@demo.test"
    exam = make_exam(student, ["demo-stack", "demo-stable-sorts", "demo-bfs", "demo-recursion"])
    login(page, student)
    start(page, exam)
    page.get_by_role("radio", name="Stack").check()
    next_question(page)
    page.get_by_role("checkbox", name="Merge sort").check()
    page.get_by_role("checkbox", name="Insertion sort").check()
    next_question(page)
    page.get_by_role("radio", name="False").check()
    next_question(page)
    page.get_by_role("textbox").first.fill("A function calling itself; the base case stops it.")
    expect(page.get_by_text("All saved")).to_be_visible()
    submit(page)

    # The teacher marks the written answer and releases.
    page.context.clear_cookies()
    login(page, TEACHER)
    page.goto(f"{BASE}/teacher/exams/{exam}/grading")
    expect(page.get_by_text("A function calling itself; the base case stops it.")).to_be_visible()
    assert axe_problems(page) == []
    page.get_by_label(re.compile("^Mark")).fill("4")
    page.keyboard.press("Enter")
    expect(page.get_by_text("1 / 1 marked")).to_be_visible()
    page.goto(f"{BASE}/teacher/exams/{exam}/results")
    page.get_by_role("button", name=re.compile("Release results")).click()
    page.get_by_role("dialog").get_by_role("button", name="Release").click()
    expect(page.get_by_text("Results released to students.")).to_be_visible()

    # 2 + 3 + 1 + 4 = 10 of 11.
    page.context.clear_cookies()
    login(page, student)
    page.goto(f"{BASE}/student/results")
    page.get_by_role("link", name=re.compile("^E2E ")).first.click()
    expect(page.get_by_text("10 / 11")).to_be_visible()
    expect(page.get_by_text("Correct:")).to_have_count(0)  # never the key
    assert axe_problems(page) == []


TWO_SUM = """import sys
d = sys.stdin.read().split()
n, t = int(d[0]), int(d[1])
seen = {}
for i, x in enumerate(map(int, d[2:2 + n])):
    if t - x in seen:
        print(seen[t - x], i)
        break
    seen.setdefault(x, i)
"""


def test_coding_exam_run_and_submit(page: Page, make_exam) -> None:  # type: ignore[no-untyped-def]
    student = "student04@demo.test"
    exam = make_exam(student, ["leetcode-1"])
    login(page, student)
    start(page, exam)
    editor = page.get_by_role("textbox", name=re.compile("^Your code"))
    editor.click()
    page.keyboard.press("Control+A")
    page.keyboard.insert_text(TWO_SUM)
    page.get_by_role("button", name="Run code").click()
    expect(page.get_by_text(re.compile("Test 1: Passed"))).to_be_visible(timeout=60_000)
    assert axe_problems(page) == []

    page.get_by_role("button", name="Submit", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="Submit").click()
    expect(page.get_by_text("Accepted").first).to_be_visible(timeout=60_000)
    submit(page)


def test_network_cut_loses_nothing(page: Page, make_exam, teacher: Api) -> None:  # type: ignore[no-untyped-def]
    student = "student05@demo.test"
    exam = make_exam(student, ["demo-stack", "demo-complexity", "demo-hash-lookup", "demo-bfs"])
    login(page, student)
    start(page, exam)
    expect(page.get_by_text("Which data structure")).to_be_visible()

    page.context.set_offline(True)
    page.get_by_role("radio", name="Stack").check()
    next_question(page)
    page.get_by_role("radio", name="O(log n)").check()
    next_question(page)
    page.get_by_role("radio", name="True").check()
    next_question(page)
    page.get_by_role("radio", name="False").check()
    expect(page.get_by_text(re.compile("Offline|not saved|waiting", re.I)).first).to_be_visible()
    time.sleep(20)  # a while offline, answering

    page.context.set_offline(False)
    expect(page.get_by_text("All saved")).to_be_visible(timeout=30_000)
    submit(page)
    rows = teacher("GET", f"/exams/{exam}/monitor")["rows"]
    assert [(r["status"], r["answered"]) for r in rows] == [("SUBMITTED", 4)]  # every answer got there
