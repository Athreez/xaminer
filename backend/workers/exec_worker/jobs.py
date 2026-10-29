"""One execution job, start to finish (TECHNICAL_ARCHITECTURE.md § 9.2; TCK-0803).

1. Fetch the test bundle through its short-lived link (or reuse it: bundles never change, so a
   copy is kept in memory by hash) and check its SHA-256.
2. Compile once, in a container.
3. Run every selected test case in a fresh container (sandbox.py) and keep the raw results.

Nothing is written to this machine's disk; the sandbox removes its containers and volumes.
Anything that goes wrong on the platform's side becomes a FAILED result, which is never a grade.
"""

import hashlib
import io
import json
import logging
import tarfile
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

import requests

from workers.exec_messages import STDERR_KEPT, CaseResult, ExecJob, ExecResult, StepResult
from workers.exec_worker.sandbox import Limits, Outcome, Sandbox

logger = logging.getLogger(__name__)

MAX_BUNDLE_BYTES = 128 * 1024 * 1024  # 50 cases of 1 MB input and output, plus room
CACHE_BYTES = 256 * 1024 * 1024


class JobError(Exception):
    """The platform couldn't do the job (bundle missing or tampered with, engine down...)."""


@dataclass(frozen=True)
class Case:
    name: str
    input: bytes
    hidden: bool


Fetch = Callable[[str], bytes]


def download(url: str) -> bytes:
    """GET the bundle, refusing anything larger than a bundle can be."""
    with requests.get(url, stream=True, timeout=(5, 60)) as response:
        if response.status_code != 200:
            raise JobError(f"bundle download failed: HTTP {response.status_code}")
        data = bytearray()
        for chunk in response.iter_content(1 << 20):
            data += chunk
            if len(data) > MAX_BUNDLE_BYTES:
                raise JobError("bundle too large")
        return bytes(data)


class BundleCache:
    """Bundles by hash, in memory, least recently used dropped first."""

    def __init__(self, fetch: Fetch = download, max_bytes: int = CACHE_BYTES) -> None:
        self.fetch = fetch
        self.max_bytes = max_bytes
        self._items: OrderedDict[str, bytes] = OrderedDict()

    def get(self, url: str, sha256: str) -> bytes:
        if sha256 in self._items:
            self._items.move_to_end(sha256)
            return self._items[sha256]
        data = self.fetch(url)
        if hashlib.sha256(data).hexdigest() != sha256:
            raise JobError("bundle hash mismatch")
        self._items[sha256] = data
        while sum(map(len, self._items.values())) > self.max_bytes and len(self._items) > 1:
            self._items.popitem(last=False)
        return data


def read_cases(bundle: bytes) -> list[Case]:
    """The cases listed in the bundle's manifest, with their input. Expected outputs are not
    needed here: this worker never compares."""
    try:
        with tarfile.open(fileobj=io.BytesIO(bundle)) as tar:
            manifest = json.load(tar.extractfile("manifest.json"))  # type: ignore[arg-type]
            cases = []
            for entry in manifest["cases"]:
                member = tar.extractfile(f"{entry['name']}.in")
                if member is None:
                    raise JobError(f"bundle has no input for case {entry['name']}")
                cases.append(Case(entry["name"], member.read(), bool(entry["hidden"])))
            return cases
    except (tarfile.TarError, KeyError, ValueError) as error:
        raise JobError(f"bundle unreadable: {error}") from error


def _step(outcome: Outcome) -> StepResult:
    return StepResult(
        exit_code=outcome.exit_code,
        stdout=outcome.stdout.decode(errors="replace"),
        stderr=outcome.stderr.decode(errors="replace")[-STDERR_KEPT:],
        time_ms=outcome.time_ms,
        timed_out=outcome.timed_out,
        memory_exceeded=outcome.memory_exceeded,
        output_exceeded=outcome.output_exceeded,
    )


def select_cases(job: ExecJob, bundles: BundleCache) -> list[Case]:
    if job.custom_input is not None:
        return [Case("custom", job.custom_input.encode(), hidden=False)]
    if not job.bundle_url or not job.bundle_sha256:
        raise JobError("job has no test bundle")
    cases = read_cases(bundles.get(job.bundle_url, job.bundle_sha256))
    return [c for c in cases if not c.hidden] if job.cases == "public" else cases


def run_job(job: ExecJob, sandbox: Sandbox, bundles: BundleCache) -> ExecResult:
    """Do the job; never raises (the result says what failed)."""
    try:
        cases = select_cases(job, bundles)
        limits = Limits(time_ms=job.time_limit_ms, memory_mb=job.memory_limit_mb)
        image = job.language.image
        result = ExecResult(
            job_id=job.job_id,
            kind=job.kind,
            status="COMPLETED",
            image_digest=sandbox.image_id(image),
        )
        with sandbox.workspace() as workspace:
            files = {job.language.source_filename: job.source.encode()}
            built = sandbox.compile(workspace, image, files, job.language.compile_cmd)
            if job.language.compile_cmd:
                result.compile = _step(built)
            if not result.compiled:
                return result  # a compile error is the student's: a result, not a failure
            for case in cases:
                outcome = sandbox.run(workspace, image, job.language.run_cmd, case.input, limits)
                result.cases.append(CaseResult(name=case.name, **_step(outcome).model_dump()))
        return result
    except JobError as error:
        return ExecResult(job_id=job.job_id, kind=job.kind, status="FAILED", error=str(error))
    except Exception as error:  # the engine, a volume, the network: never the student's fault
        logger.exception("execution job failed", extra={"job_id": job.job_id})
        return ExecResult(
            job_id=job.job_id, kind=job.kind, status="FAILED", error=type(error).__name__
        )
