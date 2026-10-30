import asyncio
import logging
import smtplib
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

from celery import shared_task

from app.core.config import get_settings

if TYPE_CHECKING:
    from workers.exec_messages import ExecResult

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
    """Send one email over SMTP. Content (it holds one-time links) and recipient are not logged.
    Test addresses (reserved domains, MAIL_SKIP_DOMAINS) are dropped, never sent."""
    from app.notifications.emails import deliverable

    settings = get_settings()
    if not deliverable(to, settings.mail_skip_domains):
        logger.info("email skipped: test address", extra={"subject_length": len(subject)})
        return
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


@shared_task(
    name="questions.build_bundle",
    autoretry_for=(OSError,),  # storage briefly down
    retry_backoff=10,
    max_retries=6,
)
def build_bundle(version_id: str) -> None:
    """Pack a coding version's test cases into its test bundle (TCK-0704). Safe to repeat."""
    key = asyncio.run(_build_bundle(uuid.UUID(version_id)))
    logger.info("test bundle ready", extra={"version_id": version_id, "built": key is not None})


async def _build_bundle(version_id: uuid.UUID) -> str | None:
    import app.db.models  # noqa: F401  (every table, so foreign keys resolve)
    from app.core.storage import Storage
    from app.db.session import create_engine, create_session_factory
    from app.questions.bundles import build

    settings = get_settings()
    engine = create_engine(settings.database_url("app"))
    try:
        return await build(create_session_factory(engine), Storage(settings), version_id)
    finally:
        await engine.dispose()


@shared_task(name="exec.result")
def receive_execution_result(result: dict[str, Any]) -> None:
    """Raw results from exec-worker: compare, score and save them (TCK-0806). Safe to repeat: a
    result whose job is no longer QUEUED is ignored."""
    from workers.exec_messages import ExecResult

    asyncio.run(_apply_result(ExecResult.model_validate(result)))


async def _apply_result(result: "ExecResult") -> None:
    import app.db.models  # noqa: F401  (every table, so foreign keys resolve)
    from app.db.session import create_engine, create_session_factory
    from app.execution.results import handle

    engine = create_engine(get_settings().database_url("app"))
    try:
        await handle(create_session_factory(engine), result)
    finally:
        await engine.dispose()


@shared_task(name="execution.delete_old_runs")
def delete_old_runs() -> None:
    """Hourly: Run Code results are practice and are deleted after 24 hours."""
    deleted = asyncio.run(_delete_old_runs())
    if deleted:
        logger.info("old code runs deleted", extra={"count": deleted})


async def _delete_old_runs() -> int:
    import app.db.models  # noqa: F401  (every table, so foreign keys resolve)
    from app.db.session import create_engine, create_session_factory
    from app.execution.runs import delete_old_runs as delete

    engine = create_engine(get_settings().database_url("app"))
    try:
        return await delete(create_session_factory(engine))
    finally:
        await engine.dispose()


@shared_task(
    name="execution.auto_submit",
    autoretry_for=(OSError,),
    retry_backoff=10,
    max_retries=6,
)
def auto_submit_drafts(attempt_id: str) -> None:
    """An attempt ended: grade each coding question's newer draft (EXE-06), then score the
    objective answers and work out the grading status (GRD-01, GRD-04). Safe to repeat."""
    asyncio.run(_auto_submit(uuid.UUID(attempt_id)))


async def _auto_submit(attempt_id: uuid.UUID) -> int:
    import app.db.models  # noqa: F401  (every table, so foreign keys resolve)
    from app.core.storage import Storage
    from app.db.session import create_engine, create_session_factory
    from app.execution.auto_submit import auto_submit
    from app.grading.objective import grade

    settings = get_settings()
    engine = create_engine(settings.database_url("app"))
    try:
        factory = create_session_factory(engine)
        submitted = await auto_submit(factory, Storage(settings), attempt_id)
        await grade(factory, attempt_id)
        return submitted
    finally:
        await engine.dispose()


@shared_task(name="exec.started")
def execution_started(job_id: str, kind: str) -> None:
    """An exec-worker picked a job up: noted, so a job that never reports back can be found."""
    asyncio.run(_with_factory(lambda factory: _started(factory, job_id, kind)))


async def _started(factory: Any, job_id: str, kind: str) -> None:
    from app.execution.recovery import started

    await started(factory, job_id, kind)


@shared_task(name="execution.retry_stuck")
def retry_stuck_jobs() -> None:
    """Every 5 minutes: send stuck submissions again; 3 starts without a result: INTERNAL_ERROR."""
    asyncio.run(_with_factory(_sweep_stuck))


async def _sweep_stuck(factory: Any) -> None:
    from app.core.storage import Storage
    from app.execution.recovery import sweep

    await sweep(factory, Storage(get_settings()))


async def _with_factory(work: Any) -> None:
    import app.db.models  # noqa: F401  (every table, so foreign keys resolve)
    from app.db.session import create_engine, create_session_factory

    engine = create_engine(get_settings().database_url("app"))
    try:
        await work(create_session_factory(engine))
    finally:
        await engine.dispose()
