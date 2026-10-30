"""200 students in one exam (TCK-1403; NFR-04, NFR-05): each logs in, starts (or resumes) the
attempt and then, like a student working, saves answers, sends the heartbeat and now and then
reloads the exam. Targets: saves and heartbeats 95 % under 300 ms, pages 95 % under 1 s.

    locust -f scripts/load/locustfile.py --headless -u 200 -r 10 -t 4m --reset-stats \
        --host http://localhost:8080

--reset-stats: the numbers are for the exam itself, once all 200 are in; the login rush before is
printed separately (`login_rush`), and a login that fails still fails the run.
"""

import itertools
import json
import os
import random
from pathlib import Path

from locust import HttpUser, between, events, task

STATE = json.loads((Path(__file__).resolve().parent / "state.json").read_text(encoding="utf-8"))
PASSWORD = os.environ["XAMINER_LOAD_PASSWORD"]
numbers = itertools.count(1)

# name: (method, 95th percentile target in ms)
TARGETS = {
    "save answer": ("PUT", 300),
    "heartbeat": ("POST", 300),
    "exam page (attempt view)": ("GET", 1000),
}


class Student(HttpUser):
    wait_time = between(3, 6)

    def on_start(self) -> None:
        n = next(numbers)
        r = self.client.post(
            "/api/v1/auth/login",
            json={"email": f"s{n:03d}@load.test", "password": PASSWORD},
            name="login",
        )
        self.client.headers["Authorization"] = "Bearer " + r.json()["access_token"]
        attempt = self.client.post(
            f"/api/v1/student/exams/{STATE['exam']}/attempts", name="start attempt"
        ).json()
        self.attempt = attempt["id"]
        self.questions = [
            (q["exam_question_id"], [o["id"] for o in q["question"]["options"]])
            for q in attempt["questions"]
            if q["question"]["type"] == "MCQ"
        ]
        self.revision = 0

    @task(6)
    def save_answer(self) -> None:
        question, options = random.choice(self.questions)
        self.revision += 1
        answer = {
            "exam_question_id": question,
            "selected_option_ids": [random.choice(options)],
            "client_revision": self.revision,
        }
        self.client.put(
            f"/api/v1/attempts/{self.attempt}/answers",
            json={"answers": [answer]},
            name="save answer",
        )

    @task(2)
    def heartbeat(self) -> None:
        self.client.post(
            f"/api/v1/attempts/{self.attempt}/heartbeat", json={"unsynced": 0}, name="heartbeat"
        )

    @task(1)
    def reload_exam(self) -> None:
        self.client.get(f"/api/v1/attempts/{self.attempt}", name="exam page (attempt view)")


login_rush: list[float] = []
login_failures = 0


@events.request.add_listener
def on_request(name, response_time, exception, **_kwargs) -> None:  # type: ignore[no-untyped-def]
    global login_failures
    if name == "login":
        login_rush.append(response_time)
        login_failures += exception is not None


@events.quitting.add_listener
def report(environment, **_kwargs) -> None:  # type: ignore[no-untyped-def]
    times = sorted(login_rush)
    if times:
        rush = times[max(0, int(len(times) * 0.95) - 1)]
        print(f"\nLogin rush: {len(times)} logins, p95 {rush:.0f} ms, {login_failures} failed")
    print("Target check (95th percentile, during the exam):")
    failed = login_failures > 0
    for name, (method, target) in TARGETS.items():
        stats = environment.stats.get(name, method)
        p95 = stats.get_response_time_percentile(0.95) or 0
        ok = p95 <= target and stats.num_failures == 0 and stats.num_requests > 0
        failed |= not ok
        print(
            f"  {name:<26} p95 {p95:>5.0f} ms (target {target} ms), {stats.num_requests} "
            f"requests, {stats.num_failures} failed  {'OK' if ok else 'MISSED'}"
        )
    environment.process_exit_code = 1 if failed else 0
