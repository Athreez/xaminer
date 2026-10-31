"""The device check before a proctored exam (PRD PRC-03, PRC-04; TCK-1001, TCK-1002): consent
first, the models downloaded, a face found by the face model on the (fake) camera with the speed
measured, the whole screen shared, then Start opens the exam. In the exam (TCK-1003..1007): the
camera corner shows, a reload asks for the screen again (the time without it recorded), and
the heartbeats show the face model running, and pictures of the screen reach the teacher."""

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
    corner = page.get_by_role("complementary", name="Proctoring")
    expect(corner.get_by_text("Proctored")).to_be_visible()
    expect(corner.get_by_label("Your camera")).to_be_visible()

    # A reload loses the shared screen: the questions wait until it's shared again.
    page.reload()
    prompt = page.get_by_role("button", name=re.compile("Return to fullscreen|Share my screen"))
    expect(prompt).to_be_visible()
    fullscreen = page.get_by_role("button", name="Return to fullscreen")
    if fullscreen.is_visible():  # headless browsers may keep fullscreen over a reload
        fullscreen.click()
    expect(page.get_by_role("heading", name="Share your screen again")).to_be_visible()
    expect(page.get_by_text("Explain recursion")).to_be_hidden()
    page.get_by_role("button", name="Share my screen").click()
    expect(page.get_by_text("Explain recursion")).to_be_visible()
    expect(corner.get_by_text("Proctored")).to_be_visible()

    # Heartbeats carry the face model's frame count: had it stood still for 60 s, the server
    # would have recorded "proctoring stopped".
    page.wait_for_timeout(70_000)
    # Leaving the page takes a picture of the screen (the periodic ones come every 20-40 s).
    page.evaluate("window.dispatchEvent(new Event('blur'))")
    page.wait_for_timeout(5_000)
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    page.get_by_role("button", name=re.compile("Review & submit")).first.click()
    page.get_by_role("button", name=re.compile("^Submit")).first.click()
    page.get_by_role("dialog").get_by_role("button", name=re.compile("^Submit")).click()
    expect(page.get_by_text(re.compile("receipt", re.I)).first).to_be_visible()

    (row,) = teacher("GET", f"/exams/{exam}/monitor")["rows"]
    detail = teacher("GET", f"/exams/{exam}/results/{row['attempt_id']}")
    kinds = [e["kind"] for e in detail["events"]]
    assert "SCREEN_SHARE_STOPPED" in kinds, kinds
    assert "SIGNAL_LOST" not in kinds and "FACE_ABSENT" not in kinds, kinds

    # The teacher sees the screen pictures (sent behind the answers, with the attempt token).
    purposes: list[str] = []
    for _ in range(20):  # the last ones may still be on their way after submitting
        pictures = teacher("GET", f"/exams/{exam}/results/{row['attempt_id']}/pictures")
        purposes = [p["purpose"] for p in pictures["screen"]]
        if "LEFT_PAGE" in purposes and "PERIODIC" in purposes:
            break
        page.wait_for_timeout(1_000)
    assert "LEFT_PAGE" in purposes and "PERIODIC" in purposes, purposes
