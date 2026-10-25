import logging
from datetime import UTC, datetime

from celery import shared_task

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
