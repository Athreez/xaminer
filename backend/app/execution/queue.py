"""Sending execution jobs to the exec-worker (TECHNICAL_ARCHITECTURE.md § 9.2).

The one place jobs leave the API; tests replace `send` (tests/db/conftest.py) so nothing reaches a
real queue.
"""

from workers.exec_messages import JOB_TASK, ExecJob


def send(job: ExecJob, queue: str) -> None:
    from workers.celery_app import enqueue  # the API's Celery client, made on first use

    enqueue(JOB_TASK, queue, job=job.model_dump())
