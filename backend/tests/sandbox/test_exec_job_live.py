"""A whole execution job on real containers (TCK-0803): bundle fetched over HTTP and checked,
compiled once, every case run, raw results back, nothing left behind. Runs with
`make sandbox-check` and in CI's runner job."""

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
from workers.exec_worker.sandbox import LABEL, Sandbox

pytestmark = pytest.mark.skipif(
    os.environ.get("SANDBOX_TESTS") != "1", reason="live sandbox: make sandbox-check"
)

CASES = [("1 2\n", "PUBLIC"), ("40 2\n", "HIDDEN"), ("-5 5\n", "HIDDEN")]
DATA, SHA = pack(
    [
        TestCase(input=i, expected_output="?", weight=1, visibility=v, order_index=n)
        for n, (i, v) in enumerate(CASES)
    ]
)


@pytest.fixture(scope="module")
def bundle_url() -> Iterator[str]:
    class Serve(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(DATA)))
            self.end_headers()
            self.wfile.write(DATA)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Serve)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/bundle.tar"
    server.shutdown()


def test_a_cpp_job_end_to_end(bundle_url: str) -> None:
    cpp = next(r for r in RUNNERS if r.key == "cpp17")
    job = ExecJob(
        job_id="live-1",
        kind="submit",
        language={  # type: ignore[arg-type]
            "key": cpp.key,
            "image": cpp.image,
            "source_filename": cpp.source_filename,
            "compile_cmd": list(cpp.compile_cmd or ()),
            "run_cmd": list(cpp.run_cmd),
        },
        time_limit_ms=2000,
        memory_limit_mb=128,
        source='#include <iostream>\nint main(){long a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}',
        bundle_url=bundle_url,
        bundle_sha256=SHA,
    )
    sandbox = Sandbox.from_env()
    result = run_job(job, sandbox, BundleCache())
    assert result.status == "COMPLETED", result.error
    assert result.image_digest and result.image_digest.startswith("sha256:")
    assert result.compile is not None and result.compile.exit_code == 0
    assert [(c.name, c.exit_code, c.stdout.strip()) for c in result.cases] == [
        ("001", 0, "3"),
        ("002", 0, "42"),
        ("003", 0, "0"),
    ]
    assert all(0 <= c.time_ms < 2000 and not c.timed_out for c in result.cases)

    public = run_job(
        job.model_copy(update={"kind": "run", "cases": "public"}), sandbox, BundleCache()
    )
    assert [c.name for c in public.cases] == ["001"]

    assert sandbox.client.containers.list(all=True, filters={"label": LABEL}) == []
    assert sandbox.client.volumes.list(filters={"label": LABEL}) == []
