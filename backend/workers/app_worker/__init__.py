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
    # Stuck code jobs are sent again; 3 starts without a result: INTERNAL_ERROR (EXE-08).
    "retry-stuck-jobs": {
        "task": "execution.retry_stuck",
        "schedule": 300.0,
        "options": {"queue": "maintenance", "expires": 240},
    },
    # Proctoring pictures to the inference-worker for the server's check (PRC-07).
    "check-proctoring-pictures": {
        "task": "proctoring.dispatch_checks",
        "schedule": 30.0,
        "options": {"queue": "maintenance", "expires": 25},
    },
    # Proctoring pictures: unchecked spot checks after 30 minutes, the rest after retention.
    "delete-proctoring-pictures": {
        "task": "proctoring.clean_up",
        "schedule": 300.0,
        "options": {"queue": "maintenance", "expires": 240},
    },
    # Run Code results are kept for 24 hours (TECHNICAL_ARCHITECTURE.md § 5).
    "delete-old-runs": {
        "task": "execution.delete_old_runs",
        "schedule": 3600.0,
        "options": {"queue": "maintenance", "expires": 3000},
    },
}

__all__ = ["app"]
