"""Load test set-up (TCK-1403): Load Test College with a teacher and 200 students, four objective
questions, Two Sum (validated on the real runner) and an exam open now for all of them. Writes
state.json for locustfile.py and burst.py. Safe to run again (a new exam each time).

    XAMINER_LOAD_PASSWORD=... python scripts/load/setup.py
"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
from seed_coding_questions import PROBLEMS, add, connect, existing, validation  # noqa: E402

BASE = os.environ.get("LOAD_BASE", "http://localhost:8080")
PASSWORD = os.environ["XAMINER_LOAD_PASSWORD"]
STUDENTS = int(os.environ.get("LOAD_STUDENTS", "200"))

seed = subprocess.run(
    ["docker", "compose", "-f", str(ROOT / "deploy" / "docker-compose.yml"), "run", "--rm",
     "--no-deps", "-T", "api", "python", "-m", "cli", "seed-load-test",
     "--students", str(STUDENTS), "--password-stdin"],
    input=PASSWORD + "\n", text=True, capture_output=True,
)  # fmt: skip
if seed.returncode:
    raise SystemExit(seed.stderr)
print("accounts:", seed.stdout.strip())

call = connect(BASE, "teacher@load.test", PASSWORD)


def options(*pairs: tuple[str, bool]) -> list[dict[str, object]]:
    return [{"label": label, "is_correct": ok} for label, ok in pairs]


questions = []
for i in range(4):
    found = call("GET", "/questions", params={"tag": f"load-{i}", "owner": "mine"})["data"]
    if found:
        questions.append(found[0]["id"])
        continue
    body = {
        "type": "MCQ",
        "body": f"Load question {i + 1}: pick B.",
        "points": "1",
        "tags": [f"load-{i}"],
        "options": options(("A", False), ("B", True), ("C", False), ("D", False)),
    }
    questions.append(call("POST", "/questions", json=body)["id"])
two_sum = next(p for p in PROBLEMS if p.number == 1)
coding = existing(call, two_sum) or add(call, two_sum)
assert validation(call, coding) == "PASSED", "Two Sum didn't validate: are the runners built?"

now = datetime.now(UTC)
exam = call(
    "POST",
    "/exams",
    json={
        "title": f"Load test {now:%H%M%S}",
        "open_at": (now - timedelta(minutes=5)).isoformat(),
        "close_at": (now + timedelta(hours=3)).isoformat(),
        "duration_min": 120,
        "run_code_enabled": True,
    },
)["id"]
picked = [{"question_id": q} for q in [*questions, coding]]
call("PUT", f"/exams/{exam}/questions", json={"questions": picked})
group = next(g["id"] for g in call("GET", "/groups", params={"q": "Load test"}))
call("POST", f"/exams/{exam}/assignments", json={"group_ids": [group], "student_ids": []})
call("POST", f"/exams/{exam}/publish")
state = {"exam": exam, "students": STUDENTS}
(HERE / "state.json").write_text(json.dumps(state), encoding="utf-8")
print("exam", exam, "ready for", STUDENTS, "students")
