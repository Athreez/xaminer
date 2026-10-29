"""exec-worker: runs untrusted code in the sandbox and sends back raw results (TCK-0803).

Run with:  celery -A workers.exec_worker worker -Q exec.validation,exec.submit,exec.run

It holds no database or storage credentials: a job brings everything it needs, including a
short-lived link to its one test bundle (SECURITY_AND_ACCESS.md § 7.2).
"""

from workers.celery_app import celery as app

app.conf.include = ["workers.exec_worker.tasks"]

__all__ = ["app"]
