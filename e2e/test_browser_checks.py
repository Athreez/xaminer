"""Browser checks in a real browser: the rules on the instructions page, fullscreen on start,
the questions hidden outside fullscreen, a paste from outside blocked (one copied inside the exam
allowed), leaving the window recorded, and the teacher reviewing it all."""

import re
import time

from playwright.sync_api import Page, expect

from conftest import BASE, TEACHER, Api, login

PASTE = """(text) => {
    const box = document.querySelector('textarea');
    box.focus();
    const data = new DataTransfer();
    data.setData('text/plain', text);
    const paste = new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true});
    box.dispatchEvent(paste);
    return paste.defaultPrevented;  // true: blocked by the exam
}"""


def test_browser_checks_end_to_end(page: Page, make_exam, teacher: Api) -> None:  # type: ignore[no-untyped-def]
    student = "student06@demo.test"
    exam = make_exam(student, ["demo-recursion", "demo-stack"], browser_checks=True)
    login(page, student)
    page.goto(f"{BASE}/student/exams/{exam}")
    rules = page.get_by_role("region").filter(has_text="Exam rules")
    expect(page.get_by_role("heading", name="Exam rules")).to_be_visible()
    expect(page.get_by_text(re.compile("paste only text you copied inside this exam"))).to_be_visible()
    del rules

    page.get_by_role("button", name=re.compile("^Start")).click()
    page.get_by_role("dialog").get_by_role("button", name="Start").click()
    expect(page.get_by_text("Explain recursion")).to_be_visible()
    assert page.evaluate("!!document.fullscreenElement"), "the exam should open in fullscreen"

    # Leaving fullscreen hides the questions until the student returns.
    page.evaluate("document.exitFullscreen()")
    expect(page.get_by_role("heading", name="This exam runs in fullscreen")).to_be_visible()
    expect(page.get_by_text("Explain recursion")).to_have_count(0)
    time.sleep(1)
    page.get_by_role("button", name="Return to fullscreen").click()
    expect(page.get_by_text("Explain recursion")).to_be_visible()

    # A paste from outside is blocked; text copied inside the exam may be pasted.
    box = page.get_by_role("textbox").first
    assert page.evaluate(PASTE, "copied from a website") is True
    expect(page.get_by_text("You can only paste text you copied in this exam.")).to_be_visible()
    expect(box).to_have_value("")
    box.fill("A base case stops it.")
    box.select_text()
    page.keyboard.press("Control+C")
    # (A test's paste event inserts nothing itself; what matters is that it isn't blocked.)
    assert page.evaluate(PASTE, "A base case stops it.") is False

    # Another window for two seconds.
    page.evaluate("window.dispatchEvent(new Event('blur'))")
    time.sleep(2)
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(page.get_by_text("Please stay on the exam page until you submit.")).to_be_visible()

    # Submit (the events go with everything else first).
    page.get_by_role("button", name=re.compile("Review & submit")).first.click()
    page.get_by_role("button", name=re.compile("^Submit")).first.click()
    page.get_by_role("dialog").get_by_role("button", name=re.compile("^Submit")).click()
    expect(page.get_by_text(re.compile("receipt", re.I)).first).to_be_visible()

    # The teacher: three events to review on the attempt, one flagged.
    (row,) = teacher("GET", f"/exams/{exam}/monitor")["rows"]
    assert row["event_count"] == 3, row
    page.context.clear_cookies()
    login(page, TEACHER)
    page.goto(f"{BASE}/teacher/exams/{exam}/results/{row['attempt_id']}")
    expect(page.get_by_text("Left fullscreen")).to_be_visible()
    expect(page.get_by_text("Paste from outside blocked")).to_be_visible()
    expect(page.get_by_text("Left the exam page")).to_be_visible()
    expect(page.get_by_text("Pending review")).to_be_visible()
    page.get_by_role("button", name="Flag").first.click()
    expect(page.get_by_text("Concerns confirmed")).to_be_visible()
