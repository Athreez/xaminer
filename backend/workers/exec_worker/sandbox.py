"""The sandbox: untrusted code runs here, in throwaway containers on `sandbox-docker`
(SECURITY_AND_ACCESS.md § 7.2; TECHNICAL_ARCHITECTURE.md § 9.4).

Assume every program is trying to escape, reach the network, read other tests or crash the machine.

- A job gets a **workspace**: a volume holding the source. The compile step (if the language has
  one) runs with it writable and leaves the program there.
- Every test case then runs in a **fresh container** with the workspace read-only and its input
  in a volume of its own, also read-only: no case can see another's input, and expected outputs
  are never in the sandbox at all.
- Every container gets the full profile (`container_settings`): no network, read-only filesystem,
  a small private `/tmp`, non-root user, every Linux capability dropped, no privilege escalation,
  Docker's default seccomp filter, memory without swap, 1 CPU, 64 processes, a 64 MB file size
  cap, output read up to 64 KB, and a kill at twice the time limit.
- `EXEC_RUNTIME=runsc` runs containers under gVisor for a second kernel boundary, if installed.

The worker never compares output or scores anything (app-worker does): this only runs and reports.
"""

import io
import os
import socket
import tarfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import docker
from docker.errors import APIError, NotFound
from docker.models.containers import Container
from docker.types import LogConfig, Mount, Ulimit
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ReadTimeout

USER = "10001:10001"  # the runner user of every image (runners/<key>/Dockerfile)
UID = 10001
OUTPUT_LIMIT = 64 * 1024  # bytes of stdout (and of stderr) kept
PIDS_LIMIT = 64
FILE_SIZE_LIMIT = 64 * 1024 * 1024  # largest file a program may write
TEMP = f"rw,noexec,nosuid,nodev,size=16m,uid={UID},gid={UID},mode=0700"
LABEL = "xaminer.sandbox"


@dataclass(frozen=True)
class Limits:
    time_ms: int
    memory_mb: int

    @property
    def kill_after_s(self) -> float:
        """Wall-clock kill: twice the time limit, so a slow start never cuts a fair run short."""
        return 2 * self.time_ms / 1000


# Compiling is our command on the student's source: generous, but still bounded.
COMPILE_LIMITS = Limits(time_ms=15_000, memory_mb=512)


@dataclass(frozen=True)
class Outcome:
    exit_code: int | None  # None: killed before it exited
    stdout: bytes  # at most OUTPUT_LIMIT
    stderr: bytes  # at most OUTPUT_LIMIT
    time_ms: int  # from the process starting to exiting, measured by the engine
    timed_out: bool  # ran past the time limit (or was killed at twice it)
    memory_exceeded: bool  # killed for using more memory than allowed
    output_exceeded: bool  # wrote more than OUTPUT_LIMIT to stdout


def container_settings(
    image: str,
    command: list[str],
    limits: Limits,
    mounts: list[Mount],
    runtime: str | None,
    owner: str = "1",
) -> dict[str, Any]:
    """Arguments for `containers.create`: the whole profile, in one place (inspection-tested)."""
    memory = f"{limits.memory_mb}m"
    settings: dict[str, Any] = {
        "image": image,
        "command": command,
        "user": USER,
        "working_dir": "/work",
        "hostname": "sandbox",
        "network_mode": "none",
        "network_disabled": True,
        "read_only": True,
        "tmpfs": {"/tmp": TEMP},
        "mounts": mounts,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges"],  # seccomp: Docker's default profile stays on
        "privileged": False,
        "ipc_mode": "private",
        "mem_limit": memory,
        "memswap_limit": memory,  # equal: no swap
        "nano_cpus": 1_000_000_000,  # 1 CPU
        "pids_limit": PIDS_LIMIT,
        "ulimits": [
            Ulimit(name="fsize", soft=FILE_SIZE_LIMIT, hard=FILE_SIZE_LIMIT),
            Ulimit(name="core", soft=0, hard=0),
        ],
        # Output is read from the engine's log, capped at 2 MB so a flood can't fill the disk. Two
        # files, not one: rotating a single file empties it, and an overflow would go unseen.
        "log_config": LogConfig(type="json-file", config={"max-size": "1m", "max-file": "2"}),
        "labels": {LABEL: owner},  # which worker made it, for cleaning up after a crash
        "stdin_open": False,
        "detach": True,
    }
    if runtime:
        settings["runtime"] = runtime
    return settings


def pack(files: dict[str, bytes]) -> bytes:
    """A tar of these files, owned by the runner user, for copying into a workspace."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.uid, info.gid = len(data), 0o644, UID, UID
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _instant(value: str) -> datetime:
    """Docker's RFC 3339 time with nanoseconds, to the microsecond Python keeps."""
    head, _, fraction = value.rstrip("Z").partition(".")
    return datetime.fromisoformat(f"{head}.{(fraction + '000000')[:6]}+00:00")


@dataclass(frozen=True)
class Workspace:
    volume: str  # the job's volume: source, then the compiled program


class Sandbox:
    def __init__(
        self, client: docker.DockerClient, runtime: str | None = None, owner: str | None = None
    ) -> None:
        self.client = client
        self.runtime = runtime
        self.owner = owner or socket.gethostname()

    @classmethod
    def from_env(cls) -> "Sandbox":
        """The engine named by DOCKER_HOST (sandbox-docker over TLS in the stack)."""
        return cls(docker.from_env(timeout=60), os.environ.get("EXEC_RUNTIME") or None)

    def image_id(self, image: str) -> str:
        """The exact image a tag points to on this engine, recorded with every evaluation."""
        return str(self.client.images.get(image).id)

    @contextmanager
    def workspace(self) -> Iterator[Workspace]:
        """A job's volume, removed afterwards whatever happens."""
        name = f"xaminer-job-{uuid.uuid4().hex}"
        self.client.volumes.create(name, labels={LABEL: self.owner})
        try:
            yield Workspace(name)
        finally:
            self._remove_volume(name)

    def compile(
        self,
        workspace: Workspace,
        image: str,
        files: dict[str, bytes],
        command: list[str] | None,
        limits: Limits = COMPILE_LIMITS,
    ) -> Outcome:
        """Put the source in the workspace and run the compile command there (writable). For
        languages without one, only the files are put in place."""
        mount = Mount("/work", workspace.volume, type="volume", read_only=False)
        container = self._create(image, command or ["true"], limits, [mount])
        try:
            container.put_archive("/work", pack(files))
            return self._run(container, limits)
        finally:
            self._remove(container)

    def run(
        self, workspace: Workspace, image: str, command: list[str], stdin: bytes, limits: Limits
    ) -> Outcome:
        """Run the program on one input, in a fresh container. The workspace is read-only."""
        input_volume = f"{workspace.volume}-in-{uuid.uuid4().hex[:12]}"
        self.client.volumes.create(input_volume, labels={LABEL: self.owner})
        try:
            self._fill(image, input_volume, {"stdin": stdin})
            mounts = [
                Mount("/work", workspace.volume, type="volume", read_only=True),
                Mount("/input", input_volume, type="volume", read_only=True),
            ]
            wrapped = ["sh", "-c", 'exec "$@" < /input/stdin', "sh", *command]
            container = self._create(image, wrapped, limits, mounts)
            try:
                return self._run(container, limits)
            finally:
                self._remove(container)
        finally:
            self._remove_volume(input_volume)

    def clean_up(self) -> int:
        """Remove containers and volumes this worker left behind, e.g. after being killed
        mid-job. Only its own: another worker's running jobs are never touched."""
        mine: dict[str, str | list[str] | bool] = {"label": f"{LABEL}={self.owner}"}
        removed = 0
        for container in self.client.containers.list(all=True, filters=mine):
            self._remove(container)
            removed += 1
        for volume in self.client.volumes.list(filters=mine):
            self._remove_volume(volume.name)
            removed += 1
        return removed

    # ------------------------------------------------------------------ internals

    def _create(
        self, image: str, command: list[str], limits: Limits, mounts: list[Mount]
    ) -> Container:
        return self.client.containers.create(
            **container_settings(image, command, limits, mounts, self.runtime, self.owner)
        )

    def _fill(self, image: str, volume: str, files: dict[str, bytes]) -> None:
        """Copy files into a volume through a container that is created but never started."""
        holder = self.client.containers.create(
            image, ["true"], user=USER, network_disabled=True, labels={LABEL: self.owner},
            mounts=[Mount("/input", volume, type="volume")],
        )  # fmt: skip
        try:
            holder.put_archive("/input", pack(files))
        finally:
            self._remove(holder)

    def _run(self, container: Container, limits: Limits) -> Outcome:
        killed = False
        container.start()
        try:
            container.wait(timeout=limits.kill_after_s)
        except (ReadTimeout, RequestsConnectionError):
            killed = True
            try:
                container.kill()
                container.wait(timeout=10)
            except (APIError, ReadTimeout, RequestsConnectionError):
                pass
        state = self.client.api.inspect_container(str(container.id))["State"]
        started, finished = _instant(state["StartedAt"]), _instant(state["FinishedAt"])
        time_ms = max(0, int((finished - started).total_seconds() * 1000))
        stdout = container.logs(stdout=True, stderr=False)
        stderr = container.logs(stdout=False, stderr=True)
        memory_exceeded = bool(state.get("OOMKilled"))
        return Outcome(
            exit_code=None if killed or memory_exceeded else state.get("ExitCode"),
            stdout=stdout[:OUTPUT_LIMIT],
            stderr=stderr[:OUTPUT_LIMIT],
            time_ms=time_ms,
            timed_out=killed or time_ms > limits.time_ms,
            memory_exceeded=memory_exceeded,
            output_exceeded=len(stdout) > OUTPUT_LIMIT,
        )

    def _remove(self, container: Container) -> None:
        try:
            container.remove(force=True)
        except NotFound:
            pass

    def _remove_volume(self, name: str) -> None:
        try:
            self.client.volumes.get(name).remove(force=True)
        except NotFound:
            pass
