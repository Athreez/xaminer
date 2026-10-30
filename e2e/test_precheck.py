"""The device check before a proctored exam (PRD PRC-03, PRC-04; TCK-1001, TCK-1002): consent
first, the models downloaded, a face found by the face model on the (fake) camera with the speed
measured, the whole screen shared, then Start opens the exam."""

import re

from playwright.sync_api import Page, expect

from conftest import BASE, Api, login


def test_device_check_then_start(page: Page, make_exam, teacher: Api) -> None:  # type: ignore[no-untyped-def]
    student = "student07@demo.test"
    exam = make_exam(student, ["demo-recursion"], proctoring_mode="VIDEO")
    login(page, student)
    page.goto(f"{BASE}/student/exams/{exam}")
    expect(page.get_by_text(re.compile("share your whole screen"))).to_be_visible()
    page.get_by_role("link", name=re.compile("Continue to checks")).click()

    # 1. Consent: the standard text, with the screen.
    expect(page.get_by_role("heading", name="Consent")).to_be_visible()
    expect(page.get_by_text(re.compile("your camera and screen"))).to_be_visible()
    page.get_by_role("button", name="I agree").click()

    # 2-3. Download, then the camera: the face model finds the face and the speed is shown.
    expect(page.get_by_role("heading", name="Camera")).to_be_visible(timeout=120_000)
    expect(page.get_by_text("We can see your face.")).to_be_visible(timeout=60_000)
    expect(page.get_by_text(re.compile(r"Face check: \d+ ms"))).to_be_visible()
    page.get_by_role("button", name="Continue").click()

    # 4. The whole screen.
    expect(page.get_by_role("heading", name="Screen sharing")).to_be_visible()
    page.get_by_role("button", name="Share my screen").click()
    expect(page.get_by_text("Your screen is shared.")).to_be_visible()
    page.get_by_role("button", name="Continue").click()

    # 5-6. Connection and screen size only warn.
    expect(page.get_by_role("heading", name="Connection")).to_be_visible()
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("button", name="Continue").click()

    expect(page.get_by_role("heading", name="Ready to start")).to_be_visible()
    page.get_by_role("button", name=re.compile("Start exam")).click()
    page.get_by_role("dialog").get_by_role("button", name="Start").click()
    page.wait_for_url(re.compile(r"/attempt/"))
    expect(page.get_by_text("Explain recursion")).to_be_visible()
