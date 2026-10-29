"""Hello-world in every runner image, under the sandbox's restrictions (TCK-0801).

    python runners/smoke_test.py                 # images on this machine's Docker
    DOCKER="docker compose -f deploy/docker-compose.yml exec -T sandbox-docker docker" \
        python runners/smoke_test.py             # images loaded into the sandbox engine

Each program reads a name from standard input and greets it, so input, compiling, running and
output are all checked. Commands come from backend/app/platform/languages.py, the same ones the
exec-worker uses. Exit status 1 if any language fails.
"""

import base64
import importlib.util
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "languages", ROOT / "backend" / "app" / "platform" / "languages.py"
)
assert spec and spec.loader
languages = importlib.util.module_from_spec(spec)
sys.modules["languages"] = languages  # dataclasses look their module up while defining
spec.loader.exec_module(languages)

HELLO = {
    "cpp17": '#include <iostream>\n#include <string>\nint main() { std::string n; std::cin >> n; std::cout << "Hello, " << n << "!" << std::endl; }\n',
    "java21": 'import java.util.Scanner;\npublic class Main { public static void main(String[] a) { System.out.println("Hello, " + new Scanner(System.in).next() + "!"); } }\n',
    "python312": 'print(f"Hello, {input()}!")\n',
    "node22": 'const n = require("fs").readFileSync(0, "utf8").trim();\nconsole.log(`Hello, ${n}!`);\n',
}

# The container profile of SECURITY_AND_ACCESS.md § 7.2 (the exec-worker applies the same).
SANDBOX = [
    "--rm", "-i",
    "--network", "none",
    "--read-only",
    "--tmpfs", "/work:rw,exec,nosuid,size=64m,uid=10001,gid=10001,mode=0700",
    "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m,uid=10001,gid=10001,mode=0700",
    "--user", "10001:10001",
    "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges",
    "--pids-limit", "64",
    "--memory", "512m", "--memory-swap", "512m",
    "--cpus", "1",
]  # fmt: skip


def run(runner: "languages.Runner", docker: list[str]) -> tuple[bool, str]:
    source = base64.b64encode(HELLO[runner.key].encode()).decode()
    steps = [f'printf %s "$SRC" | base64 -d > {runner.source_filename}']
    if runner.compile_cmd:
        steps.append(shlex.join(runner.compile_cmd))
    steps.append(shlex.join(runner.run_cmd))
    command = [
        *docker,
        "run",
        *SANDBOX,
        "-e",
        f"SRC={source}",
        runner.image,
        "sh",
        "-c",
        " && ".join(steps),
    ]
    # Bytes, not text: on Windows, text mode would turn the newline into CRLF.
    result = subprocess.run(command, input=b"Xaminer\n", capture_output=True, timeout=120)
    output = result.stdout.decode(errors="replace").strip()
    ok = result.returncode == 0 and output == "Hello, Xaminer!"
    error = result.stderr.decode(errors="replace").strip()[-400:]
    return ok, output if ok else f"exit {result.returncode}: {output} {error}"


def main() -> int:
    docker = ["docker"]
    if "--sandbox" in sys.argv:
        compose = ["docker", "compose", "-f", str(ROOT / "deploy" / "docker-compose.yml")]
        docker = [*compose, "exec", "-T", "sandbox-docker", "docker"]
    failed = 0
    for runner in languages.RUNNERS:
        started = time.monotonic()
        ok, detail = run(runner, docker)
        print(
            f"{'ok  ' if ok else 'FAIL'} {runner.key:<10} {time.monotonic() - started:5.1f}s  {detail}"
        )
        failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
