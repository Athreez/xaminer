"""language catalogue, seeded with the four supported languages

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

from app.core.ids import uuid7

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Runner images are built in TCK-0801 and pinned to digests there.
LANGUAGES = [
    {
        "key": "cpp17",
        "display_name": "C++17 (GCC)",
        "image": "xaminer-runner-cpp17:latest",
        "source_filename": "main.cpp",
        "compile_cmd": ["g++", "-std=c++17", "-O2", "-pipe", "-o", "main", "main.cpp"],
        "run_cmd": ["./main"],
        "time_multiplier": Decimal("1.0"),
    },
    {
        "key": "java21",
        "display_name": "Java 21",
        "image": "xaminer-runner-java21:latest",
        "source_filename": "Main.java",
        "compile_cmd": ["javac", "-encoding", "UTF-8", "Main.java"],
        "run_cmd": ["java", "-Xss64m", "-XX:+UseSerialGC", "-cp", ".", "Main"],
        "time_multiplier": Decimal("2.0"),
    },
    {
        "key": "python312",
        "display_name": "Python 3.12",
        "image": "xaminer-runner-python312:latest",
        "source_filename": "main.py",
        "compile_cmd": None,
        "run_cmd": ["python3", "-B", "main.py"],
        "time_multiplier": Decimal("2.5"),
    },
    {
        "key": "node22",
        "display_name": "JavaScript (Node.js 22)",
        "image": "xaminer-runner-node22:latest",
        "source_filename": "main.js",
        "compile_cmd": None,
        "run_cmd": ["node", "main.js"],
        "time_multiplier": Decimal("2.0"),
    },
]


def upgrade() -> None:
    language = op.create_table(
        "language",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("image", sa.String(length=255), nullable=False),
        sa.Column("source_filename", sa.String(length=64), nullable=False),
        sa.Column("compile_cmd", sa.ARRAY(sa.Text()), nullable=True),
        sa.Column("run_cmd", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "time_multiplier",
            sa.Numeric(precision=3, scale=1),
            server_default="1.0",
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "time_multiplier BETWEEN 1 AND 10", name=op.f("ck_language_time_multiplier_range")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_language")),
        sa.UniqueConstraint("key", name=op.f("uq_language_key")),
    )
    op.bulk_insert(language, [{"id": uuid7(), **row} for row in LANGUAGES])


def downgrade() -> None:
    op.drop_table("language")
