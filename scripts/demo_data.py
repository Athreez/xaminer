"""Demo data: Demo College with its people, a question bank and three exams, ready to show.

    make demo-data        (the stack must be up and the runners built: make up, make runners)

Asks once for a demo password (or set XAMINER_DEMO_PASSWORD); every demo account uses it:
admin@demo.test, teacher@demo.test, teacher2@demo.test, student01..student10@demo.test.

1. `seed-demo-users` (platform-admin command) makes the institution, accounts and a group.
2. As teacher@demo.test, through the API: questions of every type (three coding ones from
   seed_coding_questions.py, validated on the real runner) and three published exams:
   one open now, a quick quiz that shows results on submit, and one opening in three days.

Safe to run again: what already exists is kept.
"""

import getpass
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seed_coding_questions import PROBLEMS, Call, add, connect, existing, validation  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ["docker", "compose", "-f", str(ROOT / "deploy" / "docker-compose.yml")]
TAG = "demo"


def ask_password() -> str:
    if password := os.environ.get("XAMINER_DEMO_PASSWORD"):
        return password
    print("Choose one password for every demo account (at least 12 characters).")
    first = getpass.getpass("Demo password: ")
    if getpass.getpass("Repeat it: ") != first:
        raise SystemExit("Passwords don't match.")
    return first


def seed_users(password: str) -> None:
    command = [*COMPOSE, "run", "--rm", "--no-deps", "-T", "api"]
    command += ["python", "-m", "cli", "seed-demo-users", "--password-stdin"]
    done = subprocess.run(command, input=password + "\n", text=True, capture_output=True)
    if done.returncode != 0:
        raise SystemExit(f"Creating the demo accounts failed:\n{done.stderr.strip()}")
    print(done.stdout.strip())


def options(*labels: tuple[str, bool]) -> list[dict[str, Any]]:
    return [{"label": label, "is_correct": right} for label, right in labels]


OBJECTIVE = [
    {
        "key": "complexity",
        "type": "MCQ",
        "body": "What is the time complexity of binary search on a sorted array of n items?",
        "points": "2",
        "options": options(("O(n)", False), ("O(log n)", True), ("O(n log n)", False), ("O(1)", False)),
    },
    {
        "key": "stack",
        "type": "MCQ",
        "body": "Which data structure works **last in, first out**?",
        "points": "2",
        "options": options(("Queue", False), ("Stack", True), ("Heap", False), ("Linked list", False)),
    },
    {
        "key": "python-list",
        "type": "MCQ",
        "body": "What does this print?\n\n```python\nxs = [1, 2, 3]\nprint(xs[-1])\n```",
        "points": "2",
        "negative_marks": "0.5",
        "options": options(("1", False), ("3", True), ("-1", False), ("An error", False)),
    },
    {
        "key": "stable-sorts",
        "type": "MSQ",
        "body": "Which of these sorting algorithms are **stable**? Choose all that apply.",
        "points": "3",
        "msq_scoring": "PARTIAL",
        "options": options(
            ("Merge sort", True), ("Insertion sort", True), ("Quick sort", False), ("Heap sort", False)
        ),
    },
    {
        "key": "hash-lookup",
        "type": "TRUE_FALSE",
        "body": "Looking up a key in a hash table takes O(1) time on average.",
        "points": "1",
        "options": options(("True", True), ("False", False)),
    },
    {
        "key": "bfs",
        "type": "TRUE_FALSE",
        "body": "Depth-first search always finds the shortest path in an unweighted graph.",
        "points": "1",
        "options": options(("True", False), ("False", True)),
    },
]

WRITTEN = [
    {
        "key": "recursion",
        "type": "DESCRIPTIVE",
        "body": "Explain recursion. What is a **base case**, and what happens without one?",
        "points": "5",
        "rubric": "2 marks: a function calling itself on a smaller problem. 2 marks: the base case "
        "stops it. 1 mark: without one it never stops (stack overflow).",
    },
    {
        "key": "array-vs-list",
        "type": "DESCRIPTIVE",
        "body": "Compare an array and a linked list: one advantage of each, with an example.",
        "points": "5",
        "rubric": "Array: O(1) access by index. Linked list: O(1) insert/delete at a known node. "
        "1 mark for a fitting example.",
    },
]

CODING = (1, 9, 7)  # Two Sum, Palindrome Number, Reverse Integer


def bank(call: Call) -> dict[str, str]:
    """The demo questions by key, created where missing. Coding ones are validated."""
    ids: dict[str, str] = {}
    for q in OBJECTIVE + WRITTEN:
        tag = f"{TAG}-{q['key']}"
        found = call("GET", "/questions", params={"tag": tag, "owner": "mine"})["data"]
        if found:
            ids[q["key"]] = found[0]["id"]
            continue
        body = {k: v for k, v in q.items() if k != "key"} | {"tags": [TAG, tag]}
        ids[q["key"]] = call("POST", "/questions", json=body)["id"]
    started = []
    for p in (p for p in PROBLEMS if p.number in CODING):
        q_id = existing(call, p)
        if q_id is None:
            q_id = add(call, p)
            started.append((p, q_id))
        ids[f"leetcode-{p.number}"] = q_id
    for p, q_id in started:
        status = validation(call, q_id)
        if status != "PASSED":
            raise SystemExit(f"{p.title} didn't pass validation ({status}). Are the runners built?")
    print(f"question bank: {len(ids)} questions")
    return ids


def exams(call: Call, ids: dict[str, str]) -> None:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    group = next(g["id"] for g in call("GET", "/groups", params={"q": "CSE 2nd year"}))
    plans = [
        {
            "title": "Programming Fundamentals: Mid-term",
            "settings": {
                "instructions": "Answer every question. Coding questions: Run checks the examples, "
                "Submit is graded. You can come back to any question before you submit.",
                "open_at": now - timedelta(minutes=5),
                "close_at": now + timedelta(days=7),
                "duration_min": 45,
                "pass_percent": "40",
                "shuffle_options": True,
            },
            "questions": [
                "complexity", "stack", "python-list", "stable-sorts", "hash-lookup",
                "recursion", "leetcode-1", "leetcode-9",
            ],
        },
        {
            "title": "Quick Quiz: Data Structures",
            "settings": {
                "instructions": "Five quick questions. Your result appears as soon as you submit.",
                "open_at": now - timedelta(minutes=5),
                "close_at": now + timedelta(days=7),
                "duration_min": 10,
                "pass_percent": "50",
                "release_policy": "ON_SUBMIT",
                "shuffle_questions": True,
                "shuffle_options": True,
            },
            "questions": ["stack", "complexity", "stable-sorts", "hash-lookup", "bfs"],
        },
        {
            "title": "Algorithms: End-term",
            "settings": {
                "instructions": "90 minutes. Written answers are marked by your teacher.",
                "open_at": now + timedelta(days=3),
                "close_at": now + timedelta(days=3, hours=3),
                "duration_min": 90,
                "pass_percent": "40",
            },
            "questions": ["array-vs-list", "recursion", "bfs", "leetcode-7", "leetcode-1"],
        },
    ]  # fmt: skip
    mine = {e["title"] for e in call("GET", "/exams", params={"limit": 100})["data"]}
    for plan in plans:
        if plan["title"] in mine:
            print(f"kept     exam: {plan['title']}")
            continue
        settings = {
            k: v.isoformat() if isinstance(v, datetime) else v for k, v in plan["settings"].items()
        }
        exam = call("POST", "/exams", json={"title": plan["title"], **settings})["id"]
        call(
            "PUT",
            f"/exams/{exam}/questions",
            json={"questions": [{"question_id": ids[k]} for k in plan["questions"]]},
        )
        call("POST", f"/exams/{exam}/assignments", json={"group_ids": [group], "student_ids": []})
        call("POST", f"/exams/{exam}/publish")
        print(f"created  exam: {plan['title']}")


def main() -> None:
    password = ask_password()
    seed_users(password)
    port = os.environ.get("WEB_PORT", "8080")
    call = connect(f"http://localhost:{port}", "teacher@demo.test", password)
    exams(call, bank(call))
    print("\nDemo ready. Log in with the password you chose:")
    print("  admin@demo.test, teacher@demo.test, teacher2@demo.test, student01@demo.test ... student10@demo.test")


if __name__ == "__main__":
    main()
