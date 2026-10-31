import logging
from typing import Any

import requests
from celery import shared_task

from workers import queues
from workers.inference_messages import JOB_TASK, RESULT_TASK, InferenceJob, InferenceResult

logger = logging.getLogger(__name__)

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 10


def fetch(url: str) -> bytes:
    response = requests.get(url, timeout=TIMEOUT, stream=True)
    response.raise_for_status()
    data = response.raw.read(MAX_BYTES + 1, decode_content=True)
    if len(data) > MAX_BYTES:
        raise ValueError("picture too large")
    return bytes(data)


def check(job: InferenceJob) -> InferenceResult:
    from workers.inference_worker.models import look, reference

    try:
        known = reference(fetch(job.reference.url)) if job.reference else None
        return InferenceResult(
            job_id=job.job_id, findings=[look(p.id, fetch(p.url), known) for p in job.pictures]
        )
    except (requests.RequestException, OSError, ValueError) as exc:
        return InferenceResult(job_id=job.job_id, error=type(exc).__name__)


@shared_task(name=JOB_TASK)
def inspect(job: dict[str, Any]) -> None:
    """Check one job's pictures and send what was found to app-worker. Safe to repeat: app-worker
    applies the first result for a job. Pictures and links are never logged."""
    parsed = InferenceJob.model_validate(job)
    result = check(parsed)
    from workers.celery_app import celery

    celery.send_task(
        RESULT_TASK, kwargs={"result": result.model_dump()}, queue=queues.INFERENCE_RESULTS
    )
    logger.info(
        "inference job done",
        extra={"job_id": parsed.job_id, "pictures": len(parsed.pictures), "error": result.error},
    )
