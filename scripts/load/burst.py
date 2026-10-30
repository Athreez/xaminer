"""Code under load (TCK-1403; G-03, G-04): Run Code and Submit Code by many students at once.

    XAMINER_LOAD_PASSWORD=... python scripts/load/burst.py [--runs 50] [--submissions 100]

Students resume their attempt (or start it), then all at once: `--runs` students press Run
(the public example), then `--submissions` students submit a correct Two Sum. Each is timed until
its result is in. Targets: runs 95 % within 10 s, submissions 95 % graded within 60 s.
"""

import argparse
import json
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

STATE = json.loads((Path(__file__).resolve().parent / "state.json").read_text(encoding="utf-8"))
BASE = os.environ.get("LOAD_BASE", "http://localhost:8080") + "/api/v1"
PASSWORD = os.environ["XAMINER_LOAD_PASSWORD"]
TWO_SUM = """import sys
d = sys.stdin.read().split()
n, t = int(d[0]), int(d[1])
seen = {}
for i, x in enumerate(map(int, d[2:2 + n])):
    if t - x in seen:
        print(seen[t - x], i)
        break
    seen.setdefault(x, i)
"""

Student = tuple[requests.Session, str, str]  # session, attempt, coding exam question


GIVE_UP = 600  # seconds: counted as this long if it's still not done


def log_in(s: requests.Session, n: int) -> None:
    login = {"email": f"s{n:03d}@load.test", "password": PASSWORD}
    token = s.post(f"{BASE}/auth/login", json=login).json()["access_token"]
    s.headers["Authorization"] = "Bearer " + token
    s.headers["X-Load-Student"] = str(n)  # to log in again when the 15-minute token runs out


def student(n: int) -> Student:
    s = requests.Session()
    log_in(s, n)
    attempt = s.post(f"{BASE}/student/exams/{STATE['exam']}/attempts").json()
    coding = next(
        q["exam_question_id"] for q in attempt["questions"] if q["question"]["type"] == "CODING"
    )
    return s, attempt["id"], coding


def timed(kind: str, who: Student, gate: threading.Event) -> float:
    s, attempt, question = who
    path = "runs" if kind == "run" else "submissions"
    gate.wait()
    started = time.monotonic()
    r = s.post(
        f"{BASE}/attempts/{attempt}/questions/{question}/{path}",
        json={"language_key": "python312", "source": TWO_SUM},
    )
    r.raise_for_status()
    url = f"{BASE}/{path}/{r.json()['id']}"
    while time.monotonic() - started < GIVE_UP:
        r = s.get(url)
        if r.status_code == 401:
            log_in(s, int(s.headers["X-Load-Student"]))
            continue
        if r.json()["status"] not in ("QUEUED", "RUNNING"):
            return time.monotonic() - started
        time.sleep(1)
    return float(GIVE_UP)


def burst(kind: str, people: list[Student], target: float) -> bool:
    gate = threading.Event()
    with ThreadPoolExecutor(len(people)) as pool:
        futures = [pool.submit(timed, kind, who, gate) for who in people]
        time.sleep(1)
        gate.set()  # all at once
        times = sorted(f.result() for f in futures)
    p95 = times[max(0, int(len(times) * 0.95) - 1)]
    ok = p95 <= target
    print(
        f"{kind:<6} x{len(times)}: median {statistics.median(times):.1f} s, p95 {p95:.1f} s, "
        f"max {times[-1]:.1f} s (target p95 {target:.0f} s)  {'OK' if ok else 'MISSED'}"
    )
    return ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument("--submissions", type=int, default=100)
    args = parser.parse_args()
    with ThreadPoolExecutor(20) as pool:
        people = list(pool.map(student, range(1, max(args.runs, args.submissions) + 1)))
    ok = burst("run", people[: args.runs], 10) if args.runs else True
    if args.submissions:
        ok &= burst("submit", people[: args.submissions], 60)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
