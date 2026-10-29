"""runner images: versioned tags and commands that work on a read-only filesystem

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A frozen copy of app/platform/languages.py at runner version 1 (TCK-0801).
JVM = ["-XX:-UsePerfData", "-XX:+UseSerialGC", "-XX:TieredStopAtLevel=1"]
NEW = {
    "cpp17": ("xaminer-runner-cpp17:1", None, None),
    "java21": (
        "xaminer-runner-java21:1",
        ["javac", "-J-XX:-UsePerfData", "-encoding", "UTF-8", "Main.java"],
        ["java", *JVM, "-Xss64m", "-cp", ".", "Main"],
    ),
    "python312": ("xaminer-runner-python312:1", None, None),
    "node22": ("xaminer-runner-node22:1", None, None),
}
OLD = {
    "java21": (
        ["javac", "-encoding", "UTF-8", "Main.java"],
        ["java", "-Xss64m", "-XX:+UseSerialGC", "-cp", ".", "Main"],
    ),
}

language = sa.table(
    "language",
    sa.column("key", sa.String),
    sa.column("image", sa.String),
    sa.column("compile_cmd", sa.ARRAY(sa.Text)),
    sa.column("run_cmd", sa.ARRAY(sa.Text)),
)


def upgrade() -> None:
    for key, (image, compile_cmd, run_cmd) in NEW.items():
        values: dict[str, object] = {"image": image}
        if run_cmd:
            values |= {"compile_cmd": compile_cmd, "run_cmd": run_cmd}
        op.execute(language.update().where(language.c.key == key).values(**values))


def downgrade() -> None:
    for key in NEW:
        values: dict[str, object] = {"image": f"xaminer-runner-{key}:latest"}
        if key in OLD:
            values |= {"compile_cmd": OLD[key][0], "run_cmd": OLD[key][1]}
        op.execute(language.update().where(language.c.key == key).values(**values))
