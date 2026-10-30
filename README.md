# Xaminer

[![CI](https://github.com/Athreez/xaminer/actions/workflows/ci.yml/badge.svg)](https://github.com/Athreez/xaminer/actions/workflows/ci.yml)

A computer-based testing platform for colleges, with automated evaluation of coding questions and
AI-assisted webcam proctoring where the AI only flags and a teacher decides.

## Status

| Epic | Progress |
|---|---|
| E00 Foundation | ✅ Done: repo layout and checks, Docker Compose stack, FastAPI skeleton, database layer with automatic institution filter, language catalogue and `platform-admin`, Celery workers, frontend skeleton with typed API client, CI |
| E01 Authentication | ✅ Done: user and token tables, password hashing and rules, `create-admin` (TCK-0101, 0102); login, logout, logout everywhere, `/auth/me` API (TCK-0103); refresh-token rotation with theft detection (TCK-0104); invitations and password reset with emails (TCK-0105, 0201); account lockout and login rate limit (TCK-0106); permission system, every route must declare access (TCK-0107); ownership checks with 404 for anything not yours (TCK-0108); append-only audit log (TCK-0109); login, activation and password-reset pages with role-based routing (TCK-0110) |
| E03 Users and admin | ✅ Done (milestone M1): user management API with session revocation and last-admin protection (TCK-0301); student groups (TCK-0302); institution settings (TCK-0303); audit log search (TCK-0304); admin pages for users, groups, settings and the audit log (TCK-0305); CSV import with preview (TCK-0306) |
| E04 Question bank | ✅ Done: question, version and option tables, with database triggers that keep locked versions unchangeable (TCK-0401); question API: create, edit with automatic new versions, copy, archive, search by text, type, tag and owner (TCK-0402); rules for each question type with field-level errors (TCK-0403); private and institution-shared questions, read and copy only for colleagues (TCK-0404); Markdown cleaned on save and one safe renderer, `MarkdownView` (TCK-0405); image upload: checked, cleaned of EXIF, stored privately, shown through signed links (TCK-0406); student view with no answers or rubric, and a teacher preview of it (TCK-0407); teacher pages: question bank, editor for the four non-coding types with Markdown preview and image upload, student preview (TCK-0408) |
| E05 Exams | ✅ Done: exam, exam question, exam version and assignment tables, with a trigger that freezes published versions (TCK-0501); exam API: create, edit, delete drafts, archive, settings checked, only the window end editable after publishing; admin exam list page (TCK-0502); exam questions: add, remove, reorder and per-exam marks in one atomic save, shared questions usable (TCK-0503); assigning groups and students, with a student picker for teachers (TCK-0504); publish check listing what blocks publishing and what only warns, each naming what to fix (TCK-0505); publishing: pins and locks question versions and freezes the exam with a content hash (TCK-0506); teacher exam pages: list, overview, questions, settings, students, publish (TCK-0507) |
| E06 Attempt engine | ✅ Done: attempt, question order, answer and code draft tables; one active attempt per student enforced by the database (TCK-0601); timer rules: deadline, remaining time, 60 s grace, start cut-off, in `domain_core` (TCK-0602); student exam list (available, upcoming, completed) and detail (TCK-0603); starting an attempt: checks, fixed deadline, per-student shuffled order, full exam without answers, safe to repeat, resume (TCK-0604); autosave of answers, review flags and code drafts, order-safe by revision, refused after the grace (TCK-0605); heartbeat with server time, teacher actions and upload token, buffered in Redis (TCK-0606); submit with receipt, auto-submit when an overdue attempt is touched, and a sweeper every 30 s (TCK-0607); teacher actions on attempts: extend, force-submit, void, each with a reason (TCK-0608); teacher preview attempts on drafts and published exams, never in results (TCK-0609); exam-screen sync: on-device outbox (IndexedDB), priority uploader with backoff, server clock (TCK-0610); the exam screen: header with timer, save and connection status, question navigator, answer controls, forward-only mode, teacher preview (TCK-0611); review and submit, receipt, automatic submit at time up, "answers restored" banner, log in again without leaving the exam (TCK-0612); student dashboard (available now, upcoming, completed) and instructions page with Start, countdown to opening, and the reason when an exam can't be started (TCK-0613); network test: 2 minutes offline mid-exam while answering, 0 lost answers, status correct throughout, all saved within a second of reconnecting (TCK-0614) |
| E07 Coding questions | ✅ Done: coding setup, test case and reference solution tables; limits checked by the database, frozen with published versions (TCK-0701); API for the coding setup, languages, test cases (add, edit, reorder, delete; 50 at most) and reference solutions, with a list of what still blocks validation (TCK-0702); validation: every reference solution runs on every test case in the sandbox, report with per-case times and a warning over half the time limit, edits reset it, publishing needs it to pass (TCK-0705); the coding question editor: Problem, Languages & limits (CodeMirror starter code, effective limits), Test cases, Validate with the live report (TCK-0706); hidden test cases read through one module only (a test fails the build otherwise), student view of coding questions with public examples, leak test over every student-facing response (TCK-0703); test bundles: app-worker packs a version's test cases into a reproducible tar in storage, named by its SHA-256, rebuilt after every change (TCK-0704) |
| E08 Code execution | ✅ Done: runner images for C++17, Java 21, Python 3.12 and Node 22 (bases pinned by digest, non-root, read-only), loaded into the sandbox engine; a hello-world runs in each under the sandbox's restrictions, in CI too (TCK-0801); the sandbox: a fresh container per test case on sandbox-docker with the full security profile, the job's program read-only and each case's input in a volume of its own; inspection and break-out tests (`make sandbox-check`, CI) (TCK-0802); exec-worker job flow: fetch the bundle by a short-lived link, check its hash, compile once, run each case, raw results back on `exec.results`, nothing left behind (TCK-0803); output comparison in `domain_core` (exact, trimmed, token by token, numeric within 1e-6) with test vectors for line endings, trailing newlines, empty output and floats (TCK-0804); coding score and verdict in `domain_core` (partial or all-or-nothing, half-up rounding, PRD worked example 6.25 / PARTIAL) (TCK-0805); code run, submission, evaluation and test case result tables; app-worker compares, scores and saves results with weights, keeps the counted submission (best or last) and moves grading on; a repeated result changes nothing; platform failures get no score (TCK-0806); Run Code API: public test cases or the student's own input, one run at a time, 8 s apart, 20 per question, results never show hidden cases, deleted after 24 h (TCK-0808); Submit Code API: graded on every case, 5 s apart, never over the limit (counter under a lock), accepted in the 60 s grace, hidden cases shown as pass/fail only, history with the counted submission for the student and the exam's owner (TCK-0809); when an attempt ends, each coding question's newer draft is submitted and graded automatically, not counted toward the limit (TCK-0810); stuck jobs: every 5 min a job that started and went silent is sent again (never one that is only waiting), 3 starts without a result give INTERNAL_ERROR with no score; an exec-worker cleans up its own sandbox leftovers when it starts; killing it mid-job loses nothing (TCK-0811); attack tests: sleep, fork bombs (shell and C++), disk fill, and a search of the whole sandbox for a hidden expected output, secrets or the Docker socket (TCK-0812); run with custom input in the exam screen (TCK-0813); re-evaluation: a teacher re-runs a coding question's submissions with its current validated test cases, changed released scores keep a revision (TCK-0814) |
| E06c Coding in the exam screen | ✅ Done: coding panel with problem, CodeMirror per language with kept drafts, Run (public tests, not graded, cooldown, custom input) and Submit (confirmed, graded, hidden tests as pass/fail only), results with visible whitespace and differences, submission history with the counted one, a submitted tick in the navigator (TCK-0615) |
| E09 Grading and results | ✅ Done: objective scoring in `domain_core` (single choice, multiple choice all-or-nothing or partial, true/false, negative marks, half-up rounding, total never below 0) (TCK-0901); objective answers graded by app-worker when an attempt ends, unanswered ones scored 0, safe to repeat (TCK-0902); grading status per attempt: pending, awaiting coding, awaiting manual, complete, worked out from what is still unscored; coding questions take the counted submission's score (TCK-0903); marking API: queue per descriptive question with students anonymous unless asked, mark 0 to points with feedback, audited (TCK-0904); results computed when grading completes (total, %, pass/fail), release refused until every attempt is graded, "on submit" exams release at once (TCK-0905); students see their own released results only, no keys (TCK-0906); a changed released score needs a reason and keeps a revision (TCK-0907); grading page (one answer at a time, keyboard only, names hidden), results table with release and its reason, attempt detail, student results list and detail (TCK-0908 to TCK-0910); teacher dashboard with answers to mark and results to release |
| E14 Quality and demo | In progress: demo set-up: HTTPS with a self-signed certificate for this laptop's Wi-Fi address, real email through Gmail, `make demo-data` with Demo College, its people, questions and three exams; README "Run the demo" (TCK-1407) |

`exec-worker` and `inference-worker` are placeholders until their tickets. The design lives in
[`docs/`](docs/):

| Document | What it covers |
|---|---|
| [PRD.md](docs/PRD.md) | Features, rules, scope |
| [TECHNICAL_ARCHITECTURE.md](docs/TECHNICAL_ARCHITECTURE.md) | Services, stack, database, API, key flows |
| [SECURITY_AND_ACCESS.md](docs/SECURITY_AND_ACCESS.md) | Permissions, sandbox, proctoring privacy, threats |
| [FRONTEND_SPEC.md](docs/FRONTEND_SPEC.md) | Pages, routes, exam screen |
| [FEATURE_TICKETS.md](docs/FEATURE_TICKETS.md) | Tickets and build order |

## Planned stack

React + Vite (frontend) · FastAPI (backend) · PostgreSQL · Redis + Celery · SeaweedFS (S3 storage) · Docker sandboxes for
code execution · MediaPipe (in-browser) and PyTorch/ONNX (server) for proctoring · Docker Compose.

## Repository layout

```
backend/     FastAPI app (app/), pure grading rules (domain_core/), Celery workers (workers/), CLI (cli/)
frontend/    React + Vite app
runners/     Docker images for each programming language
deploy/      Docker Compose and nginx config
docs/        Design documents
scripts/     Demo set-up and sample data (make demo-https, make demo-data)
```

## Development setup

**Prerequisites**

| Tool | Version | Notes |
|---|---|---|
| Git | any recent | |
| Node.js + npm | 22+ | |
| uv | 0.13+ | `pip install --user uv`; then `uv python install 3.12` |
| GNU Make | any | Ships with Git for Windows' bash |
| Docker Desktop | latest | With the WSL 2 backend on Windows. Needed from TCK-0002 onwards |

On Windows, make sure these are on `PATH`: the folder containing `uv.exe` (for a `pip --user` install,
`%APPDATA%\Python\Python311\Scripts`) and `%USERPROFILE%\.local\bin`.

**First time**

```sh
make setup                 # installs backend and frontend dependencies
uvx pre-commit install     # optional: run checks before every commit
```

**Checks**

```sh
make check                 # lint + type-check + tests, backend and frontend
make format                # auto-format everything
```

Some tests use the running stack (Postgres database `xaminer_test`, Redis database 15), so run
`make up` first; without it they are skipped (in CI, `REQUIRE_SERVICES=1` makes them fail instead).

**Frontend development** (hot reload; the stack must be up for the API):

```sh
cd frontend && npm run dev     # http://localhost:5173, /api is proxied to localhost:8080
```

After changing backend endpoints, regenerate the typed client and commit both generated files:

```sh
make api-client                # writes frontend/src/api/openapi.json and schema.d.ts
```

**Database migrations** (from `backend/`, with the stack running):

```sh
uv run alembic revision --autogenerate -m "what changed"   # then review the generated file
make up                                                      # the `migrate` service applies it
```

For `alembic` commands on the host, export `POSTGRES_HOST=127.0.0.1`, `POSTGRES_PORT=15432` and
`DB_MIGRATOR_PASSWORD` from `deploy/.env` first.

## Continuous integration

Every push to `main` and every pull request runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml):

| Job | Checks |
|---|---|
| Backend | ruff, mypy, pytest against real Postgres and Redis (`REQUIRE_SERVICES=1`: nothing is skipped). Test files run in parallel; tests marked `serial` run after |
| Frontend | oxlint, Prettier, type check, production build, and that `make api-client` output is committed |
| Docker images | every service image builds |

## Running the full stack

```sh
cp deploy/.env.example deploy/.env    # then change every "change-me" value
make up                               # build and start all services
make ps                               # status
make logs                             # follow logs
make down                             # stop (data volumes are kept)
make runners                          # build the language runners into the sandbox (once, and after changes)
make runners-check sandbox-check      # hello-world in each language; sandbox break-out tests
```

| URL | What |
|---|---|
| http://localhost:8080 | The app (nginx → React; `/api/` → FastAPI) |
| http://localhost:8080/api/v1/health | API health check |
| http://localhost:8080/api/v1/docs | Interactive API docs (not in production) |
| http://localhost:8080/theme | Theme preview: every colour and component, light and dark |
| http://localhost:8025 | Mailpit — emails sent in development |
| `localhost:8333` | Object storage S3 API (SeaweedFS) |
| `localhost:15432` | PostgreSQL, for local DB tools |
| `localhost:16379` | Redis, for local tools and tests |

### Platform admin commands

Set-up tasks for whoever runs the platform (not an in-app role). The stack must be up. Values are
passed as variables, which works the same in PowerShell, cmd and bash:

```sh
make create-institution NAME="ABC College"                     # timezone defaults to Asia/Kolkata
make create-institution NAME="XYZ School" TIMEZONE=Europe/London
make create-admin INSTITUTION="ABC College" EMAIL=admin@abc.edu NAME="Asha Rao"
#   asks for the password twice (hidden); it is never passed on the command line
make invite-user INSTITUTION="ABC College" EMAIL=ravi@abc.edu NAME="Ravi Kumar" ROLE=STUDENT ROLL_NO=CSE-042
#   emails an activation link (ROLE: ADMIN, TEACHER or STUDENT; ROLL_NO optional); run again to re-send
make list-institutions
make list-languages
```

### Sample coding questions

Adds ten classic problems (LeetCode 1 to 10, retold for stdin/stdout, with public and hidden
tests and a Python reference) to a teacher's question bank and validates them. Asks for the
password; problems already there are skipped:

```sh
uv run --no-project --with requests python scripts/seed_coding_questions.py --email teacher@abc.edu
```

Emails in development go to Mailpit (http://localhost:8025); nothing is really sent. For real
email, see "Real email (Gmail)" below.

## Run the demo

From a fresh laptop to a demo that other laptops and phones on the same Wi-Fi can use.

1. Install Git, Docker Desktop, Node.js 22+, uv and make (table under "Development setup"), then:

   ```sh
   git clone https://github.com/Athreez/xaminer.git && cd xaminer
   make setup
   cp deploy/.env.example deploy/.env      # then replace every change-me value
   ```

2. HTTPS for this laptop's Wi-Fi address (browsers need it for the camera on other devices):

   ```sh
   make demo-https        # finds the address; or: make demo-https IP=192.168.1.20
   ```

   It sets `CERT_HOSTS` and `PUBLIC_BASE_URL` in `deploy/.env` and prints the demo address,
   e.g. `https://192.168.1.20:8443`. Run it again if the laptop's Wi-Fi address changes.

3. Start everything and build the language runners (the first time takes a while):

   ```sh
   make up
   make runners
   ```

4. Demo data: asks for one password used by every demo account.

   ```sh
   make demo-data
   ```

   | Account | Role |
   |---|---|
   | `admin@demo.edu` | Admin of Demo College |
   | `teacher@demo.edu`, `teacher2@demo.edu` | Teachers (the first owns the sample exams) |
   | `student01@demo.edu` … `student10@demo.edu` | Students in the group "CSE 2nd year" |

   Exams: **Programming Fundamentals: Mid-term** (open now; every question type, two coding),
   **Quick Quiz: Data Structures** (open now; results show on submit) and **Algorithms:
   End-term** (opens in three days). Running it again keeps what's there.

5. Open the demo address on any device on the Wi-Fi. The certificate is self-signed, so each
   browser warns once: choose **Advanced → Proceed**. If other devices can't connect, allow
   port 8443 in the Windows firewall (Docker Desktop usually asks the first time).

On the laptop itself, http://localhost:8080 keeps working too.

### Real email (Gmail)

Emails (invitations, password resets) go to Mailpit until you set this up:

1. Turn on 2-Step Verification for the Google account (myaccount.google.com → Security).
2. Create an app password at https://myaccount.google.com/apppasswords (name it "Xaminer");
   Google shows 16 letters once.
3. In `deploy/.env`:

   ```sh
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_STARTTLS=true
   SMTP_USERNAME=you@gmail.com
   SMTP_PASSWORD=abcdefghijklmnop          # the app password, without spaces
   MAIL_FROM=Xaminer <you@gmail.com>
   ```

4. `make up`, then send yourself a test: as the demo admin, invite a user with your own email.

Links in emails use `PUBLIC_BASE_URL` (set by `make demo-https`). Gmail sends at most about 500
emails a day from a personal account.

Services: `web`, `api`, `app-worker`, `scheduler`, `exec-worker`, `sandbox-docker`, `inference-worker`,
`postgres`, `redis`, `storage` (+ one-off `storage-init` that creates the buckets), `mailpit`. See
[architecture § 3](docs/TECHNICAL_ARCHITECTURE.md#3-services).
