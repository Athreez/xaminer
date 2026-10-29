import asyncio
import logging
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage

from celery import shared_task

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@shared_task(name="system.ping", ignore_result=False)
def ping(message: str = "ping") -> dict[str, str]:
    """Round-trip check: API -> Redis -> app-worker -> result."""
    # Log facts about the input, never the input itself (it stands in for answers or code).
    logger.info("ping received", extra={"message_length": len(message)})
    return {"reply": "pong", "echo": message, "at": datetime.now(UTC).isoformat()}


@shared_task(name="system.heartbeat")
def heartbeat() -> None:
    """Scheduled by Celery Beat every 5 minutes, so the logs show the scheduler is running."""
    logger.info("scheduler heartbeat")


@shared_task(
    name="email.send",
    autoretry_for=(smtplib.SMTPException, OSError),
    retry_backoff=30,  # 30 s, 60 s, 120 s, ... while the mail server is down
    retry_backoff_max=1800,
    max_retries=8,
)
def send_email(to: str, subject: str, text: str, html: str) -> None:
    """Send one email over SMTP. Content (it holds one-time links) and recipient are not logged."""
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(message)
    logger.info("email sent", extra={"subject_length": len(subject)})


@shared_task(name="attempts.sweep")
def sweep_attempts() -> None:
    """Every 30 s: submit attempts past their deadline + 60 s grace that nobody touched (ATT-11).

    Safe to run twice or overlap: each attempt is ended by one guarded update.
    """
    ended = asyncio.run(_sweep())
    if ended:
        logger.info("overdue attempts submitted", extra={"count": ended})


async def _sweep() -> int:
    # A fresh engine per run: Celery tasks are synchronous, and asyncpg connections belong to the
    # event loop that opened them.
    from app.attempts.submit import sweep
    from app.db.session import create_engine, create_session_factory

    engine = create_engine(get_settings().database_url("app"))
    try:
        return await sweep(create_session_factory(engine))
    finally:
        await engine.dispose()
