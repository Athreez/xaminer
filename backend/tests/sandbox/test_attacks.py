"""Sandbox attack tests (PRD NFR-03; SECURITY_AND_ACCESS.md § 7.3; TCK-0812).

Programs written to escape or hurt the machine, each with its expected outcome, and nothing
escaping. Together with test_sandbox_live.py (infinite loop, memory, process count, network,
read-only filesystem, privileges, output flood). Runs with `make sandbox-check` and in CI.
"""

import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.platform.languages import RUNNERS
from app.questions.bundles import pack
from app.questions.models import TestCase
from workers.exec_messages import ExecJob
from workers.exec_worker.jobs import BundleCache, run_job
from workers.exec_worker.sandbox import Limits, Outcome, Sandbox, Workspace

pytestmark = pytest.mark.skipif(
    os.environ.get("SANDBOX_TESTS") != "1", reason="live sandbox: make sandbox-check"
)

LANG = {r.key: r for r in RUNNERS}
PYTHON, CPP = LANG["python312"], LANG["cpp17"]
SECRET = "HIDDEN-EXPECTED-7c41f"  # in a hidden case's expected output: must never be readable


@pytest.fixture(scope="module")
def sandbox() -> Sandbox:
    return Sandbox.from_env()


@pytest.fixture
def workspace(sandbox: Sandbox) -> Iterator[Workspace]:
    with sandbox.workspace() as ws:
        yield ws


def python(sandbox: Sandbox, ws: Workspace, code: str, limits: Limits) -> Outcome:
    sandbox.compile(ws, PYTHON.image, {"main.py": code.encode()}, None)
    return sandbox.run(ws, PYTHON.image, list(PYTHON.run_cmd), b"", limits)


def test_sleeping_is_killed_like_looping(sandbox: Sandbox, workspace: Workspace) -> None:
    out = python(
        sandbox, workspace, "import time\ntime.sleep(60)\nprint('woke')\n", Limits(1000, 64)
    )
    assert out.timed_out and out.exit_code is None and b"woke" not in out.stdout


def test_shell_fork_bomb_is_contained(sandbox: Sandbox, workspace: Workspace) -> None:
    code = "import os\nos.system(\"f(){ f|f& };f\")\nprint('survived')\n"
    out = python(sandbox, workspace, code, Limits(2000, 128))
    assert out.timed_out or out.exit_code is not None  # stopped by the process cap or the clock
    # The machine is fine: the next program runs normally, in time.
    after = python(sandbox, workspace, "print('still fine')\n", Limits(2000, 64))
    assert (after.exit_code, after.stdout.strip(), after.timed_out) == (0, b"still fine", False)


def test_cpp_fork_loop_is_contained(sandbox: Sandbox, workspace: Workspace) -> None:
    code = (
        b"#include <unistd.h>\n#include <cstdio>\n"
        b'int main(){int n=0;while(fork()>=0)n++;printf("%d\\n",n);}'
    )
    built = sandbox.compile(workspace, CPP.image, {"main.cpp": code}, list(CPP.compile_cmd or ()))
    assert built.exit_code == 0, built.stderr
    out = sandbox.run(workspace, CPP.image, list(CPP.run_cmd), b"", Limits(2000, 128))
    if out.stdout.strip():
        assert int(out.stdout.split()[0]) < 64  # the first fork that failed ended the loop
    assert out.time_ms < 2 * 2000 + 2000


def test_disk_fill_stops_at_the_private_tmp(sandbox: Sandbox, workspace: Workspace) -> None:
    code = (
        "import os\nwritten = 0\nblock = b'x' * (1 << 20)\n"
        "try:\n"
        "    with open('/tmp/fill', 'wb') as f:\n"
        "        for _ in range(200):\n"
        "            f.write(block); f.flush(); written += len(block)\n"
        "except OSError as e:\n"
        "    print('stopped', e.errno)\n"
        "print(written // (1 << 20))\n"
        "for path in ('/fill', '/work/fill', '/input/fill', '/home/fill', '/var/tmp/fill'):\n"
        "    try:\n        open(path, 'wb').write(b'x'); print('wrote', path)\n"
        "    except OSError:\n        pass\n"
    )
    lines = python(sandbox, workspace, code, Limits(5000, 128)).stdout.decode().split()
    assert lines[0] == "stopped" and int(lines[2]) <= 16  # the 16 MB /tmp, nothing more
    assert "wrote" not in lines


def test_nothing_secret_or_foreign_is_readable(sandbox: Sandbox) -> None:
    """A whole job through the worker: the hidden expected output is nowhere in the sandbox, nor
    are the platform's secrets, the Docker socket, other users' files or the host."""
    data, digest = pack(
        [
            TestCase(
                input="probe",
                expected_output="public answer",
                weight=1,
                visibility="PUBLIC",
                order_index=0,
            ),
            TestCase(
                input="probe", expected_output=SECRET, weight=1, visibility="HIDDEN", order_index=1
            ),
        ]
    )

    class Serve(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Serve)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    probe = (
        "import os\n"
        "found = []\n"
        "for top in ('/', ):\n"
        "    for root, dirs, files in os.walk(top):\n"
        "        if root.startswith(('/proc', '/sys', '/dev')):\n"
        "            dirs[:] = []; continue\n"
        "        for name in files:\n"
        "            try:\n"
        "                with open(os.path.join(root, name), 'rb') as f:\n"
        # Put together at run time, so the program's own source doesn't hold the marker.
        f"                    if (b'{SECRET[:8]}' + b'{SECRET[8:]}') in f.read(4 << 20):\n"
        "                        found.append(os.path.join(root, name))\n"
        "            except OSError:\n"
        "                pass\n"
        "print('found', found)\n"
        "print('docker socket', os.path.exists('/var/run/docker.sock'))\n"
        "words = ('REDIS', 'POSTGRES', 'DOCKER', 'S3', 'SECRET', 'PASSWORD', 'JWT')\n"
        "secrets = [k for k in os.environ if any(w in k for w in words)]\n"
        "print('env secrets', secrets)\n"
        "try:\n    open('/etc/shadow').read(); print('shadow readable')\n"
        "except OSError:\n    print('shadow refused')\n"
        "print('work', sorted(os.listdir('/work')))\n"
        "print('input', sorted(os.listdir('/input')))\n"
    )
    job = ExecJob(
        job_id="attack-1",
        kind="submit",
        language={  # type: ignore[arg-type]
            "key": PYTHON.key,
            "image": PYTHON.image,
            "source_filename": PYTHON.source_filename,
            "compile_cmd": None,
            "run_cmd": list(PYTHON.run_cmd),
        },
        time_limit_ms=20_000,
        memory_limit_mb=256,
        source=probe,
        bundle_url=f"http://127.0.0.1:{server.server_port}/b.tar",
        bundle_sha256=digest,
    )
    result = run_job(job, sandbox, BundleCache())
    server.shutdown()
    assert result.status == "COMPLETED", result.error
    for case in result.cases:  # the public and the hidden case: same view of the sandbox
        lines = case.stdout.splitlines()
        assert lines[0] == "found []", lines[0]  # the hidden expected output never got in
        assert lines[1:5] == [
            "docker socket False",
            "env secrets []",
            "shadow refused",
            "work ['main.py']",
        ], lines
        assert lines[5] == "input ['stdin']"
        assert SECRET not in case.stdout
