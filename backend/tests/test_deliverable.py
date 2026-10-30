"""Emails never leave for test addresses (TCK-1301): reserved domains and MAIL_SKIP_DOMAINS."""

import pytest

from app.notifications.emails import deliverable


@pytest.mark.parametrize(
    ("address", "skip", "ok"),
    [
        ("asha@gmail.com", "", True),
        ("student01@demo.test", "", False),
        ("a@example", "", False),
        ("a@mail.example", "", False),
        ("a@x.invalid", "", False),
        ("a@localhost", "", False),
        ("teacher@test.com", "test.com, check.edu", False),
        ("a@sub.check.edu", "test.com,check.edu", False),
        ("a@notcheck.edu", "check.edu", True),
        ("A@Test.COM", "test.com", False),
    ],
)
def test_deliverable(address: str, skip: str, ok: bool) -> None:
    assert deliverable(address, skip) is ok
