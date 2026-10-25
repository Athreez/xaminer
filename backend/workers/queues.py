"""Queue names (TECHNICAL_ARCHITECTURE.md § 9.2, § 10), shared by the API and all workers."""

DEFAULT = "default"
GRADING = "grading"
MAINTENANCE = "maintenance"
NOTIFY = "notify"

# Code execution: consumed by exec-worker. Results come back on EXEC_RESULTS to app-worker.
EXEC_VALIDATION = "exec.validation"
EXEC_RUN = "exec.run"
EXEC_SUBMIT = "exec.submit"
EXEC_RESULTS = "exec.results"

# Proctoring checks: consumed by inference-worker. Verdicts come back on INFERENCE_RESULTS.
INFERENCE_VERIFY = "inference.verify"
INFERENCE_RESULTS = "inference.results"

# What each worker listens to.
APP_WORKER_QUEUES = [DEFAULT, GRADING, EXEC_RESULTS, INFERENCE_RESULTS, MAINTENANCE, NOTIFY]
EXEC_WORKER_QUEUES = [EXEC_VALIDATION, EXEC_SUBMIT, EXEC_RUN]
INFERENCE_WORKER_QUEUES = [INFERENCE_VERIFY]
