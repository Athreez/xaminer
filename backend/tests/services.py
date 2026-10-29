"""Settings for tests that need the running Docker stack (Postgres, Redis).

Values come from deploy/.env, overridable by environment variables. If a service isn't reachable,
such tests are skipped, unless REQUIRE_SERVICES=1 (CI), where they fail instead.
"""

import os
import socket
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND.parent / "deploy" / ".env"


def _load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    values.update(os.environ)
    return values


ENV = _load_env()
HOST = ENV.get("TEST_SERVICES_HOST", "127.0.0.1")

# Parallel runs (pytest -n) name their workers gw0, gw1, ...; one process alone counts as gw0.
WORKER = int(os.environ.get("PYTEST_XDIST_WORKER", "gw0").removeprefix("gw"))
# Each worker gets its own Redis database, counting down from 15 (the app itself uses 0), so
# rate limits and counters of one worker never touch another's.
REDIS_DB = 15 - WORKER
assert REDIS_DB > 0, "too many test workers for Redis; use --maxprocesses 8"


def require(port: int, name: str) -> None:
    """Skip (or fail in CI) unless a service is listening on HOST:port."""
    try:
        socket.create_connection((HOST, port), timeout=2).close()
    except OSError:
        message = f"{name} not reachable at {HOST}:{port}; start the stack with `make up`."
        if ENV.get("REQUIRE_SERVICES") == "1":
            pytest.fail(message)
        pytest.skip(message)
