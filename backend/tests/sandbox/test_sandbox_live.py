"""The sandbox on real containers (TCK-0802): the profile as the engine applied it, and programs
that try to break out. Needs Docker and the runner images (`make runners`); runs with
`make sandbox-check` and in CI's runner job, skipped otherwise.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
from docker.types import Mount

from app.platform.languages import RUNNERS
from workers.exec_worker.sandbox import LABEL, OUTPUT_LIMIT, Limits, Outcome, Sandbox, Workspace

pytestmark = pytest.mark.skipif(
    os.environ.get("SANDBOX_TESTS") != "1", reason="live sandbox: make sandbox-check"
)

LANG = {r.key: r for r in RUNNERS}
PYTHON = LANG["python312"]
FAST = Limits(time_ms=2000, memory_mb=128)


@pytest.fixture(scope="module")
def sandbox() -> Sandbox:
    return Sandbox.from_env()


@pytest.fixture
def workspace(sandbox: Sandbox) -> Iterator[Workspace]:
    with sandbox.workspace() as ws:
        yield ws


def python(
    sandbox: Sandbox, ws: Workspace, code: str, stdin: bytes = b"", limits: Limits = FAST
) -> Outcome:
    sandbox.compile(ws, PYTHON.image, {"main.py": code.encode()}, None)
    return sandbox.run(ws, PYTHON.image, list(PYTHON.run_cmd), stdin, limits)


def test_the_engine_applies_the_whole_profile(sandbox: Sandbox, workspace: Workspace) -> None:
    mounts = [Mount("/work", workspace.volume, type="volume", read_only=True)]
    container = sandbox._create(PYTHON.image, ["true"], FAST, mounts)  # inspected, never started
    try:
        config = sandbox.client.api.inspect_container(container.id)
    finally:
        container.remove(force=True)
    host = config["HostConfig"]
    assert host["NetworkMode"] == "none"
    assert host["ReadonlyRootfs"] is True
    assert host["Privileged"] is False
    assert host["CapDrop"] == ["ALL"]
    assert "no-new-privileges" in host["SecurityOpt"]
    assert not any("seccomp" in opt for opt in host["SecurityOpt"])  # default filter kept
    assert host["Memory"] == host["MemorySwap"] == 128 * 1024 * 1024
    assert host["NanoCpus"] == 1_000_000_000
    assert host["PidsLimit"] == 64
    assert host["Tmpfs"]["/tmp"].startswith("rw,noexec,nosuid,nodev,size=16m")
    assert {u["Name"]: u["Hard"] for u in host["Ulimits"]}["fsize"] == 64 * 1024 * 1024
    assert host["LogConfig"]["Config"]["max-size"] == "1m"
    assert config["Config"]["User"] == "10001:10001"
    assert [m["ReadOnly"] for m in host["Mounts"]] == [True]
    assert config["Config"]["Labels"][LABEL] == sandbox.owner  # whose leftovers to clean up


SUM = {
    "cpp17": b'#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}',
    "java21": (
        b"import java.util.*;public class Main{public static void main(String[] x){"
        b"Scanner s=new Scanner(System.in);System.out.println(s.nextInt()+s.nextInt());}}"
    ),
    "python312": b"a, b = map(int, input().split())\nprint(a + b)\n",
    "node22": (
        b'const [a,b]=require("fs").readFileSync(0,"utf8").trim().split(" ").map(Number);'
        b"console.log(a+b);"
    ),
}


def test_every_language_compiles_once_and_runs_each_case(sandbox: Sandbox) -> None:
    for runner in RUNNERS:
        with sandbox.workspace() as ws:
            compile_cmd = list(runner.compile_cmd) if runner.compile_cmd else None
            files = {runner.source_filename: SUM[runner.key]}
            built = sandbox.compile(ws, runner.image, files, compile_cmd)
            assert built.exit_code == 0, (runner.key, built.stderr)
            for stdin, expected in ((b"1 2\n", b"3"), (b"40 2\n", b"42")):
                out = sandbox.run(ws, runner.image, list(runner.run_cmd), stdin, Limits(5000, 256))
                assert (out.exit_code, out.stdout.strip()) == (0, expected), (runner.key, out)


def test_compile_errors_come_back(sandbox: Sandbox, workspace: Workspace) -> None:
    cpp = LANG["cpp17"]
    files = {"main.cpp": b"int main( {"}
    built = sandbox.compile(workspace, cpp.image, files, list(cpp.compile_cmd or ()))
    assert built.exit_code != 0 and b"error" in built.stderr


def test_infinite_loop_is_killed(sandbox: Sandbox, workspace: Workspace) -> None:
    out = python(sandbox, workspace, "while True:\n    pass\n", limits=Limits(1000, 128))
    assert out.timed_out and out.exit_code is None


def test_memory_hog_is_stopped(sandbox: Sandbox, workspace: Workspace) -> None:
    out = python(sandbox, workspace, "x = bytearray(512 * 1024 * 1024)\nprint('allocated')\n")
    assert out.memory_exceeded or out.exit_code != 0
    assert b"allocated" not in out.stdout


def test_process_count_is_capped(sandbox: Sandbox, workspace: Workspace) -> None:
    code = (
        "import subprocess\nstarted = 0\n"
        "for _ in range(200):\n"
        "    try:\n        subprocess.Popen(['sleep', '3']); started += 1\n"
        "    except OSError:\n        break\n"
        "print(started)\n"
    )
    out = python(sandbox, workspace, code, limits=Limits(5000, 128))
    assert int(out.stdout.strip() or 0) < 64


def test_no_network(sandbox: Sandbox, workspace: Workspace) -> None:
    code = (
        "import socket\n"
        "try:\n    socket.create_connection(('1.1.1.1', 53), timeout=2); print('connected')\n"
        "except OSError:\n    print('blocked')\n"
    )
    assert python(sandbox, workspace, code).stdout.strip() == b"blocked"


def test_filesystem_is_read_only_except_tmp(sandbox: Sandbox, workspace: Workspace) -> None:
    code = (
        "import os\n"
        "for path in ('/etc/x', '/work/x', '/input/x', '/tmp/x'):\n"
        "    try:\n        open(path, 'w').write('x'); print(path, 'written')\n"
        "    except OSError:\n        print(path, 'refused')\n"
        "print(sorted(os.listdir('/input')))\n"
    )
    lines = python(sandbox, workspace, code).stdout.decode().splitlines()
    assert lines == [
        "/etc/x refused",
        "/work/x refused",
        "/input/x refused",
        "/tmp/x written",
        "['stdin']",  # only this case's input: no other case, no expected output
    ]


def test_runs_unprivileged(sandbox: Sandbox, workspace: Workspace) -> None:
    code = (
        "import os\nprint(os.getuid(), os.getgid())\n"
        "for line in open('/proc/self/status'):\n"
        "    if line.startswith(('CapEff', 'NoNewPrivs')):\n"
        "        print(' '.join(line.split()))\n"
    )
    out = python(sandbox, workspace, code).stdout.decode()
    assert out.startswith("10001 10001")
    assert "CapEff: 0000000000000000" in out and "NoNewPrivs: 1" in out


def test_output_flood_is_cut(sandbox: Sandbox, workspace: Workspace) -> None:
    out = python(sandbox, workspace, "import sys\nsys.stdout.write('x' * 2_000_000)\n")
    assert out.output_exceeded and len(out.stdout) == OUTPUT_LIMIT


def test_nothing_is_left_behind(sandbox: Sandbox) -> None:
    marker = uuid.uuid4().hex
    with sandbox.workspace() as ws:
        python(sandbox, ws, f"print('{marker}')")
    leftovers = sandbox.client.containers.list(all=True, filters={"label": LABEL})
    volumes = sandbox.client.volumes.list(filters={"name": ws.volume})
    assert leftovers == [] and volumes == []
