"""exec-worker: runs untrusted code in the sandbox and sends back raw results (TCK-0803).

Run with:  celery -A workers.exec_worker worker -Q exec.validation,exec.submit,exec.run

It holds no database or storage credentials: a job brings everything it needs, including a
short-lived link to its one test bundle (SECURITY_AND_ACCESS.md § 7.2).
"""

import logging
from typing import Any

from celery.signals import worker_ready

from workers.celery_app import celery as app

app.conf.include = ["workers.exec_worker.tasks"]


@worker_ready.connect
def _clean_up(**_: Any) -> None:
    """Containers and volumes left by this worker before a crash or kill are removed at start."""
    from workers.exec_worker.sandbox import Sandbox

    removed = Sandbox.from_env().clean_up()
    if removed:
        logging.getLogger(__name__).info("sandbox leftovers removed", extra={"count": removed})


__all__ = ["app"]
