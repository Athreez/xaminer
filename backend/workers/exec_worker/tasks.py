import logging
from functools import cache
from typing import Any

from celery import shared_task

from workers import queues
from workers.exec_messages import JOB_TASK, RESULT_TASK, ExecJob
from workers.exec_worker.jobs import BundleCache, run_job
from workers.exec_worker.sandbox import Sandbox

logger = logging.getLogger(__name__)


@cache
def _sandbox() -> Sandbox:
    return Sandbox.from_env()  # one engine connection per worker process


@cache
def _bundles() -> BundleCache:
    return BundleCache()


@shared_task(name=JOB_TASK)
def execute(job: dict[str, Any]) -> None:
    """Run one job and send its raw results to app-worker. Safe to repeat: app-worker keeps the
    first result for a job and ignores the rest. Source code and outputs are never logged."""
    parsed = ExecJob.model_validate(job)
    result = run_job(parsed, _sandbox(), _bundles())
    from workers.celery_app import celery

    celery.send_task(RESULT_TASK, kwargs={"result": result.model_dump()}, queue=queues.EXEC_RESULTS)
    logger.info(
        "execution job done",
        extra={
            "job_id": parsed.job_id,
            "kind": parsed.kind,
            "status": result.status,
            "cases": len(result.cases),
        },
    )
