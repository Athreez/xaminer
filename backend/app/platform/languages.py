"""The four languages students can use (PRD CQ-02) and how their runner images build and run code.

The single source in code. The `language` table holds a copy (seeded and updated by migrations;
`tests/db/test_languages_db.py` checks the two agree), and `runners/smoke_test.py` uses this to
compile and run a hello-world in every image.

Runner images are built from `runners/<key>/Dockerfile` (`make runners`). Student code sits in
`/work` and is compiled and run there as a non-root user, with the rest of the filesystem read-only
and a small private `/tmp`. Bump `RUNNER_VERSION` whenever a Dockerfile changes.

No imports from the rest of the app: the smoke test loads this file on its own.
"""

from dataclasses import dataclass
from decimal import Decimal

RUNNER_VERSION = 2


@dataclass(frozen=True)
class Runner:
    key: str
    display_name: str
    source_filename: str
    compile_cmd: tuple[str, ...] | None
    run_cmd: tuple[str, ...]
    time_multiplier: Decimal  # slower languages get more time: limit x multiplier (CQ-03)

    @property
    def image(self) -> str:
        return f"xaminer-runner-{self.key}:{RUNNER_VERSION}"


# The JVM normally writes performance data under /tmp, which is read-only in the sandbox.
_JVM = ("-XX:-UsePerfData", "-XX:+UseSerialGC", "-XX:TieredStopAtLevel=1")

RUNNERS = (
    Runner(
        key="cpp17",
        display_name="C++17 (GCC)",
        source_filename="main.cpp",
        compile_cmd=("g++", "-std=c++17", "-O2", "-pipe", "-o", "main", "main.cpp"),
        run_cmd=("./main",),
        time_multiplier=Decimal("1.0"),
    ),
    Runner(
        key="java21",
        display_name="Java 21",
        source_filename="Main.java",
        compile_cmd=("javac", "-J-XX:-UsePerfData", "-encoding", "UTF-8", "Main.java"),
        run_cmd=("java", *_JVM, "-Xss64m", "-cp", ".", "Main"),
        time_multiplier=Decimal("2.0"),
    ),
    Runner(
        key="python312",
        display_name="Python 3.12",
        source_filename="main.py",
        compile_cmd=None,
        run_cmd=("python3", "-B", "main.py"),
        time_multiplier=Decimal("2.5"),
    ),
    Runner(
        key="node22",
        display_name="JavaScript (Node.js 22)",
        source_filename="main.js",
        compile_cmd=None,
        run_cmd=("node", "main.js"),
        time_multiplier=Decimal("2.0"),
    ),
)
