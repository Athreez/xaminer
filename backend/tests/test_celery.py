import logging
from collections.abc import Iterator

import pytest
from celery import Celery
from celery.contrib.testing.worker import start_worker

from app.core.logging import JsonFormatter
from tests.services import ENV, HOST, REDIS_DB, require
from workers import queues
from workers.celery_app import create_celery

REDIS_PORT = int(ENV.get("TEST_REDIS_PORT", ENV.get("REDIS_HOST_PORT", "16379")))


def test_json_only_and_at_least_once() -> None:
    conf = create_celery("check", redis_url="redis://localhost:1/0").conf
    assert conf.accept_content == ["json"]  # never pickle: untrusted workers share Redis
    assert conf.task_serializer == "json"
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True


def test_every_queue_has_exactly_one_consumer() -> None:
    consumers = (
        queues.APP_WORKER_QUEUES + queues.EXEC_WORKER_QUEUES + queues.INFERENCE_WORKER_QUEUES
    )
    declared = [
        value for name, value in vars(queues).items() if name.isupper() and isinstance(value, str)
    ]
    assert sorted(consumers) == sorted(declared)


def test_untrusted_workers_never_consume_trusted_queues() -> None:
    trusted = set(queues.APP_WORKER_QUEUES)
    assert not trusted & set(queues.EXEC_WORKER_QUEUES)
    assert not trusted & set(queues.INFERENCE_WORKER_QUEUES)


@pytest.fixture
def live_app() -> Iterator[Celery]:
    require(REDIS_PORT, "Redis")
    password = ENV.get("REDIS_PASSWORD", "")
    # A database of its own keeps test messages away from the real queues in database 0.
    app = create_celery("test", redis_url=f"redis://:{password}@{HOST}:{REDIS_PORT}/{REDIS_DB}")
    import workers.app_worker.tasks  # noqa: F401  (registers the shared tasks)

    with start_worker(app, perform_ping_check=False, loglevel="WARNING"):
        yield app


def test_task_round_trip_through_redis(live_app: Celery, caplog: pytest.LogCaptureFixture) -> None:
    marker = "student-answer-must-not-be-logged"
    with caplog.at_level(logging.INFO):
        result = live_app.send_task("system.ping", kwargs={"message": marker}, queue=queues.DEFAULT)
        reply = result.get(timeout=15)
    assert reply["reply"] == "pong"
    assert reply["echo"] == marker

    # Neither the task arguments nor its return value may appear in any log line.
    formatter = JsonFormatter()
    lines = [formatter.format(r) for r in caplog.records]
    assert any("succeeded" in line for line in lines)
    assert not any(marker in line for line in lines)
