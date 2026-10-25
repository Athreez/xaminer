"""app-worker: trusted background jobs (grading, saving results, cleanup, email).

Run with:  celery -A workers.app_worker worker   (and `beat` for the scheduler)
"""

from workers.celery_app import celery as app

app.conf.include = ["workers.app_worker.tasks"]
app.conf.beat_schedule = {
    # Proves the scheduler is alive; real schedules (sweeper, cleanup) are added by later tickets.
    "system-heartbeat": {"task": "system.heartbeat", "schedule": 300.0},
}

__all__ = ["app"]
