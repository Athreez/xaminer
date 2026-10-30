"""Email content and sending (PRD NOT-01). The API builds the message; app-worker sends it.

Links carry their token after `#`: browsers never send that part to the server, so tokens can't end
up in nginx or API logs (SECURITY_AND_ACCESS.md § 5.5).
"""

from dataclasses import dataclass
from html import escape

from workers import queues
from workers.celery_app import enqueue

INVITE_DAYS = 7
RESET_HOURS = 1


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    html: str


def _html(paragraphs: list[str], button_text: str, link: str) -> str:
    body = "".join(f"<p>{escape(p)}</p>" for p in paragraphs)
    return (
        '<div style="font-family:system-ui,sans-serif;font-size:15px;line-height:1.5;color:#111">'
        f"{body}"
        f'<p><a href="{escape(link)}" style="display:inline-block;padding:10px 18px;'
        'background:#111;color:#fff;border-radius:6px;text-decoration:none">'
        f"{escape(button_text)}</a></p>"
        f'<p style="color:#666;font-size:13px">Or open this link: {escape(link)}</p>'
        "</div>"
    )


def invitation_email(
    *, to: str, full_name: str, institution_name: str, token: str, base_url: str
) -> Email:
    link = f"{base_url.rstrip('/')}/activate#token={token}"
    lines = [
        f"Hello {full_name},",
        f"{institution_name} has created a Xaminer account for you.",
        f"Set your password to activate it. The link works once and expires in {INVITE_DAYS} days.",
    ]
    return Email(
        to=to,
        subject=f"Your Xaminer account at {institution_name}",
        text="\n\n".join([*lines, link, "If you weren't expecting this, ignore this email."]),
        html=_html(
            [*lines[:2], lines[2], "If you weren't expecting this, ignore this email."],
            "Set my password",
            link,
        ),
    )


def password_reset_email(
    *, to: str, full_name: str, institution_name: str, token: str, base_url: str
) -> Email:
    link = f"{base_url.rstrip('/')}/reset-password#token={token}"
    lines = [
        f"Hello {full_name},",
        f"Someone asked to reset the password of your Xaminer account at {institution_name}.",
        f"Choose a new password with the link below. It works once and expires in {RESET_HOURS} "
        "hour. Resetting logs you out on every device.",
    ]
    note = "If it wasn't you, ignore this email. Your password stays the same."
    return Email(
        to=to,
        subject="Reset your Xaminer password",
        text="\n\n".join([*lines, link, note]),
        html=_html([*lines, note], "Choose a new password", link),
    )


RESERVED = {"test", "example", "invalid", "localhost"}  # RFC 2606: never real mailboxes


def deliverable(address: str, skip_domains: str = "") -> bool:
    """False for addresses on reserved test domains or on MAIL_SKIP_DOMAINS: nothing is sent."""
    domain = address.rsplit("@", 1)[-1].strip().lower()
    skipped = {d.strip().lower() for d in skip_domains.split(",") if d.strip()}
    return not (
        domain.rsplit(".", 1)[-1] in RESERVED
        or domain in skipped
        or any(domain.endswith("." + d) for d in skipped)
    )


def queue_email(email: Email) -> None:
    """Hand the email to app-worker. Returns at once; sending happens in the background."""
    enqueue(
        "email.send",
        queues.NOTIFY,
        to=email.to,
        subject=email.subject,
        text=email.text,
        html=email.html,
    )


def exam_assigned_email(
    *, to: str, full_name: str, exam_title: str, when: str, duration: str, link: str
) -> Email:
    """A student was given an exam (sent when it's published, or on a later assignment)."""
    lines = [
        f"Hello {full_name},",
        f"You have a new exam: {exam_title}.",
        f"It opens {when} and lasts {duration} once you start.",
        "Open it before it starts to read the instructions.",
    ]
    return Email(
        to=to,
        subject=f"New exam: {exam_title}",
        text="\n\n".join([*lines, link]),
        html=_html(lines, "View the exam", link),
    )


def result_released_email(*, to: str, full_name: str, exam_title: str, link: str) -> Email:
    lines = [
        f"Hello {full_name},",
        f"Your result for {exam_title} is out: your score, each question and your teacher's "
        "feedback.",
    ]
    return Email(
        to=to,
        subject=f"Your result: {exam_title}",
        text="\n\n".join([*lines, link]),
        html=_html(lines, "See my result", link),
    )
