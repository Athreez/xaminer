# Load test (TCK-1403)

How Xaminer copes with a full exam hall: 200 students in one exam (NFR-04), saves and pages
(NFR-05), Run Code (G-03) and submissions (G-04). Run on 2026-10-30.

## How to run it

```sh
# deploy/.env: LOGIN_RATE_PER_MINUTE=1000 while testing (200 logins come from one machine), then remove it
XAMINER_LOAD_PASSWORD=... python scripts/load/setup.py      # Load Test College, 200 students, an exam
XAMINER_LOAD_PASSWORD=... locust -f scripts/load/locustfile.py --headless -u 200 -r 10 -t 4m \
    --reset-stats --host http://localhost:8080             # 200 students working for 4 minutes
XAMINER_LOAD_PASSWORD=... python scripts/load/burst.py --runs 30 --submissions 30   # code, all at once
```

Each simulated student logs in, starts the exam, then saves an answer, sends the heartbeat or
reloads the exam every 3 to 6 seconds. The burst has many students press Run or Submit (a correct
Two Sum, six test cases) at the same moment and times each until its result is in.

## The machine

A laptop: 8 CPUs, 4 GB for Docker. Docker's disk is on a **spinning hard disk** (drive D); the
laptop's SSD (drive C) was too full. That disk turns out to decide the results.

## Results

**200 students at once: every request succeeded** (over 6,000 saves per 4-minute run, 0 errors).

| Request (95th percentile) | Target | Hard disk | Commits not waiting for the disk* |
|---|---|---|---|
| Save an answer | 300 ms | 690 ms | **76 ms** |
| Heartbeat | 300 ms | 440 ms | **71 ms** |
| Exam page | 1 s | 270 ms | **40 ms** |
| 200 logins in 20 s | — | 9.5 s | 4.7 s |

\* Postgres `synchronous_commit = off` for one run, to see the cost of the slow disk alone (not
safe to keep: answers confirmed just before a power cut could be lost). A single save took
100 ms on the hard disk even with nobody else on the system; a heartbeat, which writes to the
database at most once a minute, 12 ms.

| Code, all at once (6 parallel jobs) | Target (95th percentile) | Median | 95th percentile |
|---|---|---|---|
| 30 students press Run | 10 s | 105 s | 177 s |
| 30 students submit | 60 s | 241 s | 403 s |
| one Run alone | 10 s | 12 s | |
| one submission alone | 60 s | 32 s | |

Every run and submission got its result. Each test case runs in a fresh locked-down container,
and starting containers on the hard disk takes seconds: about 4–5 graded submissions a minute.

## What it means

- **The application meets the speed targets; this laptop's disk doesn't.** With the disk taken
  out of the picture, saves and heartbeats are four times under target.
- **Code grading needs a server**: an SSD and more CPUs. Throughput grows with
  `EXEC_CONCURRENCY` (parallel code jobs) as long as CPU and memory allow.
- For a classroom demo on this laptop (tens of students, a few submissions at a time) it is fine.
  For 200 students, deploy to a VM with an SSD (about 4 CPUs, 8 GB) and run the test again there.

## Changes the test led to

- Password checks (Argon2, slow on purpose) ran on the API's event loop, so a login rush froze
  every other request, and 200 at once ran the server out of memory (7.5 % of logins failed).
  They now run in a thread, at most two at a time per API process: 0 failed.
- The API runs 4 processes instead of 1 (`API_WORKERS`).
- Settings for the test and for bigger machines: `LOGIN_RATE_PER_MINUTE`, `EXEC_CONCURRENCY`.
