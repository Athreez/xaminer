"""Messages between the API / app-worker and the exec-worker (TECHNICAL_ARCHITECTURE.md § 9.2).

A job carries everything the exec-worker needs, because it has no database or storage access:
the language's image and commands, the limits, the source, and a short-lived link to the test
bundle with its hash. The result is raw: outputs, times and what went wrong. Comparing outputs
and scoring happen in app-worker, never in the worker that ran the code.
"""

from typing import Literal

from pydantic import BaseModel, Field

JOB_TASK = "exec.job"  # consumed by exec-worker on exec.validation / exec.run / exec.submit
RESULT_TASK = "exec.result"  # consumed by app-worker on exec.results

STDERR_KEPT = 4096  # characters of each case's stderr sent back (stdout: the sandbox's 64 KB)


class LanguageSpec(BaseModel):
    key: str
    image: str
    source_filename: str
    compile_cmd: list[str] | None
    run_cmd: list[str]


class ExecJob(BaseModel):
    job_id: str
    kind: Literal["validation", "run", "submit"]
    language: LanguageSpec
    time_limit_ms: int = Field(
        ge=100, le=25_000, description="Already times the language multiplier"
    )
    memory_limit_mb: int = Field(ge=16, le=512)
    source: str = Field(max_length=262_144)
    bundle_url: str | None = Field(default=None, description="Pre-signed, a few minutes")
    bundle_sha256: str | None = None
    cases: Literal["all", "public"] = "all"  # Run Code uses the public ones only
    custom_input: str | None = Field(
        default=None, max_length=65_536, description="Run with this input instead of test cases"
    )


class StepResult(BaseModel):
    exit_code: int | None  # None: killed
    stdout: str
    stderr: str
    time_ms: int
    timed_out: bool
    memory_exceeded: bool
    output_exceeded: bool


class CaseResult(StepResult):
    name: str  # "001" (position in the bundle) or "custom"
    memory_kb: int | None = None  # not measured yet


class ExecResult(BaseModel):
    job_id: str
    status: Literal["COMPLETED", "FAILED"]  # FAILED: the platform failed, never the student
    error: str | None = None
    image_digest: str | None = None
    compile: StepResult | None = None  # None for languages without a compile step
    cases: list[CaseResult] = []

    @property
    def compiled(self) -> bool:
        return self.compile is None or (self.compile.exit_code == 0 and not self.compile.timed_out)
