from email.message import EmailMessage
from typing import Any, ClassVar

import pytest

from app.core.config import Settings
from app.notifications.emails import invitation_email, password_reset_email
from workers.app_worker import tasks


def test_invitation_link_keeps_token_out_of_the_url_path() -> None:
    email = invitation_email(
        to="r@abc.edu",
        full_name="Ravi K",
        institution_name="ABC College",
        token="TOKEN123",
        base_url="https://exam.abc.edu/",
    )
    assert "https://exam.abc.edu/activate#token=TOKEN123" in email.text
    assert "https://exam.abc.edu/activate#token=TOKEN123" in email.html
    assert email.subject == "Your Xaminer account at ABC College"
    assert "7 days" in email.text


def test_reset_link_and_wording() -> None:
    email = password_reset_email(
        to="r@abc.edu",
        full_name="Ravi K",
        institution_name="ABC College",
        token="TOKEN123",
        base_url="http://localhost:8080",
    )
    assert "http://localhost:8080/reset-password#token=TOKEN123" in email.text
    assert "1 hour" in email.text
    assert "logs you out on every device" in email.text


def test_names_are_escaped_in_html() -> None:
    email = invitation_email(
        to="r@abc.edu",
        full_name="<script>alert(1)</script>",
        institution_name="A & B",
        token="T",
        base_url="http://x",
    )
    assert "<script>" not in email.html
    assert "&lt;script&gt;" in email.html
    assert "A &amp; B" in email.html


class FakeSMTP:
    sent: ClassVar[list[EmailMessage]] = []
    calls: ClassVar[list[str]] = []

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.calls.append(f"connect {host}:{port}")

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def starttls(self) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login {user}")

    def send_message(self, message: EmailMessage) -> None:
        self.sent.append(message)


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.sent, FakeSMTP.calls = [], []
    monkeypatch.setattr(tasks.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def test_send_email_plain_dev_server(
    fake_smtp: type[FakeSMTP], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "get_settings", lambda: Settings(smtp_host="mailpit"))
    tasks.send_email("r@abc.edu", "Hi", "plain body", "<p>html body</p>")
    assert fake_smtp.calls == ["connect mailpit:1025"]  # no TLS, no login for Mailpit
    message = fake_smtp.sent[0]
    assert message["To"] == "r@abc.edu"
    assert message["From"] == "Xaminer <no-reply@xaminer.local>"
    assert message.get_body(("plain",)).get_content().strip() == "plain body"  # type: ignore[union-attr]
    assert "html body" in message.get_body(("html",)).get_content()  # type: ignore[union-attr]


def test_send_email_real_server_uses_tls_and_login(
    fake_smtp: type[FakeSMTP], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_starttls=True,
        smtp_username="mailer",
        smtp_password="pw",  # type: ignore[arg-type]
    )
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)
    tasks.send_email("r@abc.edu", "Hi", "t", "<p>h</p>")
    assert fake_smtp.calls == ["connect smtp.example.com:587", "starttls", "login mailer"]
