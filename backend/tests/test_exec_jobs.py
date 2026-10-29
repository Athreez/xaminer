"""Execution job flow with a stand-in sandbox (TCK-0803). The real sandbox: tests/sandbox."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.questions.bundles import pack
from app.questions.models import TestCase
from workers.exec_messages import ExecJob, ExecResult
from workers.exec_worker.jobs import BundleCache, JobError, run_job
from workers.exec_worker.sandbox import Limits, Outcome, Workspace


def outcome(stdout: bytes = b"", exit_code: int | None = 0, **flags: Any) -> Outcome:
    values: dict[str, Any] = {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": b"",
        "time_ms": 12,
        "timed_out": False,
        "memory_exceeded": False,
        "output_exceeded": False,
    } | flags
    return Outcome(**values)


class FakeSandbox:
    """Echoes each case's input back, upper-cased; records what it was asked to do."""

    def __init__(self, compiled: Outcome | None = None) -> None:
        self.compiled = compiled or outcome()
        self.inputs: list[bytes] = []
        self.files: dict[str, bytes] = {}

    def image_id(self, image: str) -> str:
        return "sha256:abc"

    @contextmanager
    def workspace(self) -> Iterator[Workspace]:
        yield Workspace("vol")

    def compile(self, ws: Workspace, image: str, files: dict[str, bytes], command: Any) -> Outcome:
        self.files = files
        return self.compiled

    def run(self, ws: Workspace, image: str, command: Any, stdin: bytes, limits: Limits) -> Outcome:
        self.inputs.append(stdin)
        return outcome(stdin.upper())


def bundle(*cases: tuple[str, str]) -> tuple[bytes, str]:
    rows = [
        TestCase(input=i, expected_output="?", weight=1, visibility=v, order_index=n)
        for n, (i, v) in enumerate(cases)
    ]
    return pack(rows)


DATA, SHA = bundle(("public one", "PUBLIC"), ("hidden two", "HIDDEN"), ("hidden three", "HIDDEN"))


def job(**overrides: Any) -> ExecJob:
    values: dict[str, Any] = {
        "job_id": "j1",
        "kind": "validation",
        "language": {
            "key": "cpp17",
            "image": "xaminer-runner-cpp17:2",
            "source_filename": "main.cpp",
            "compile_cmd": ["g++", "main.cpp"],
            "run_cmd": ["./main"],
        },
        "time_limit_ms": 1000,
        "memory_limit_mb": 128,
        "source": "int main() {}",
        "bundle_url": "http://storage/b.tar",
        "bundle_sha256": SHA,
    } | overrides
    return ExecJob.model_validate(values)


def cache(data: bytes = DATA) -> BundleCache:
    return BundleCache(fetch=lambda url: data)


def test_runs_every_case_in_order_and_reports_raw_output() -> None:
    sandbox = FakeSandbox()
    result = run_job(job(), sandbox, cache())  # type: ignore[arg-type]
    assert result.status == "COMPLETED" and result.image_digest == "sha256:abc"
    assert sandbox.files == {"main.cpp": b"int main() {}"}
    assert [(c.name, c.stdout) for c in result.cases] == [
        ("001", "PUBLIC ONE"),
        ("002", "HIDDEN TWO"),
        ("003", "HIDDEN THREE"),
    ]
    assert result.compile is not None and result.compile.exit_code == 0
    ExecResult.model_validate(result.model_dump())  # travels as JSON


def test_run_code_uses_public_cases_only() -> None:
    sandbox = FakeSandbox()
    result = run_job(job(kind="run", cases="public"), sandbox, cache())  # type: ignore[arg-type]
    assert [c.name for c in result.cases] == ["001"] and sandbox.inputs == [b"public one"]


def test_custom_input_needs_no_bundle() -> None:
    sandbox = FakeSandbox()
    result = run_job(  # type: ignore[arg-type]
        job(kind="run", custom_input="my input", bundle_url=None, bundle_sha256=None),
        sandbox,
        cache(b"unused"),
    )
    assert [(c.name, c.stdout) for c in result.cases] == [("custom", "MY INPUT")]


def test_compile_error_is_a_result_with_no_cases() -> None:
    failed = outcome(exit_code=1, stderr=b"main.cpp:1: error: expected ';'")
    result = run_job(job(), FakeSandbox(compiled=failed), cache())  # type: ignore[arg-type]
    assert result.status == "COMPLETED" and not result.compiled and result.cases == []
    assert result.compile is not None and "expected ';'" in result.compile.stderr


def test_interpreted_languages_report_no_compile_step() -> None:
    python = {
        "key": "python312",
        "image": "xaminer-runner-python312:2",
        "source_filename": "main.py",
        "compile_cmd": None,
        "run_cmd": ["python3", "main.py"],
    }
    result = run_job(job(language=python), FakeSandbox(), cache())  # type: ignore[arg-type]
    assert result.compile is None and result.compiled and len(result.cases) == 3


def test_tampered_or_missing_bundle_fails_the_job_not_the_student() -> None:
    tampered = run_job(job(), FakeSandbox(), cache(DATA + b"x"))  # type: ignore[arg-type]
    assert (tampered.status, tampered.error) == ("FAILED", "bundle hash mismatch")
    garbage = b"not a tar"
    broken = run_job(  # type: ignore[arg-type]
        job(bundle_sha256=hashlib.sha256(garbage).hexdigest()), FakeSandbox(), cache(garbage)
    )
    assert broken.status == "FAILED" and broken.error and "unreadable" in broken.error
    none = run_job(job(bundle_url=None), FakeSandbox(), cache())  # type: ignore[arg-type]
    assert none.status == "FAILED"


def test_engine_trouble_fails_the_job() -> None:
    class Down(FakeSandbox):
        def run(self, *args: Any) -> Outcome:
            raise ConnectionError("engine unreachable")

    result = run_job(job(), Down(), cache())  # type: ignore[arg-type]
    assert (result.status, result.error, result.cases) == ("FAILED", "ConnectionError", [])


def test_bundles_are_fetched_once_and_checked() -> None:
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return DATA

    bundles = BundleCache(fetch=fetch)
    bundles.get("http://a", SHA)
    bundles.get("http://b", SHA)  # a new link to the same bundle: the cached copy is used
    assert fetched == ["http://a"]
    try:
        BundleCache(fetch=lambda url: b"evil").get("http://c", SHA)
    except JobError as error:
        assert "mismatch" in str(error)
    else:
        raise AssertionError("a bundle with the wrong hash was accepted")
