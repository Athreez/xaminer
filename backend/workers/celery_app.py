"""Shared Celery configuration for every worker and for the API (which only sends tasks).

Delivery is at-least-once: a task may run twice, so every task must be safe to repeat
(TECHNICAL_ARCHITECTURE.md § 10).
"""

from celery import Celery
from celery.app import trace
from celery.signals import setup_logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from workers import queues

# Celery's default success line includes the task's return value; ours leaves it out (no answers,
# code or evidence keys in logs, SECURITY_AND_ACCESS.md § 5.5). See also JsonFormatter.
trace.LOG_SUCCESS = "Task %(name)s[%(id)s] succeeded in %(runtime)ss"


def create_celery(name: str = "xaminer", redis_url: str | None = None) -> Celery:
    redis_url = redis_url or get_settings().redis_url.get_secret_value()
    app = Celery(name, broker=redis_url, backend=redis_url)
    app.conf.update(
        # JSON only. Never pickle: untrusted workers share this Redis, and pickle runs code.
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # Acknowledge after the task finishes, so a crashed worker's job is delivered again.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_default_queue=queues.DEFAULT,
        task_ignore_result=True,  # results travel on result queues; tasks opt in if needed
        result_expires=3600,
        timezone="UTC",
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        worker_hijack_root_logger=False,
    )
    return app


@setup_logging.connect
def _json_logging(**_: object) -> None:
    """Use our JSON log format in workers too, instead of Celery's own."""
    configure_logging(get_settings().log_level)


# The API uses this instance to send tasks by name; it never imports worker task modules.
celery = create_celery()


def enqueue(task_name: str, queue: str, **kwargs: object) -> str:
    """Send a task by name. Returns the task id."""
    result = celery.send_task(task_name, kwargs=kwargs, queue=queue)
    return str(result.id)
