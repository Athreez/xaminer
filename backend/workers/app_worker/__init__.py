"""app-worker: trusted background jobs (grading, saving results, cleanup, email).

Run with:  celery -A workers.app_worker worker   (and `beat` for the scheduler)
"""

from workers.celery_app import celery as app

app.conf.include = ["workers.app_worker.tasks"]
app.conf.beat_schedule = {
    # Proves the scheduler is alive.
    "system-heartbeat": {"task": "system.heartbeat", "schedule": 300.0},
    # Submits attempts left past their deadline + grace (ATT-11: "even if the browser is closed").
    "attempts-sweep": {
        "task": "attempts.sweep",
        "schedule": 30.0,
        "options": {"queue": "maintenance", "expires": 25},
    },
    # Run Code results are kept for 24 hours (TECHNICAL_ARCHITECTURE.md § 5).
    "delete-old-runs": {
        "task": "execution.delete_old_runs",
        "schedule": 3600.0,
        "options": {"queue": "maintenance", "expires": 3000},
    },
}

__all__ = ["app"]
