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
| E07 Coding questions | In progress: coding setup, test case and reference solution tables; limits checked by the database, frozen with published versions (TCK-0701); API for the coding setup, languages, test cases (add, edit, reorder, delete; 50 at most) and reference solutions, with a list of what still blocks validation (TCK-0702); hidden test cases read through one module only (a test fails the build otherwise), student view of coding questions with public examples, leak test over every student-facing response (TCK-0703); test bundles: app-worker packs a version's test cases into a reproducible tar in storage, named by its SHA-256, rebuilt after every change (TCK-0704) |
| E08 Code execution | In progress: runner images for C++17, Java 21, Python 3.12 and Node 22 (bases pinned by digest, non-root, read-only), loaded into the sandbox engine; a hello-world runs in each under the sandbox's restrictions, in CI too (TCK-0801); the sandbox: a fresh container per test case on sandbox-docker with the full security profile, the job's program read-only and each case's input in a volume of its own; inspection and break-out tests (`make sandbox-check`, CI) (TCK-0802) |

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

Emails in development go to Mailpit (http://localhost:8025); nothing is really sent. For real email, set
the `SMTP_*` and `PUBLIC_BASE_URL` values in `deploy/.env` (see `.env.example`).

Services: `web`, `api`, `app-worker`, `scheduler`, `exec-worker`, `sandbox-docker`, `inference-worker`,
`postgres`, `redis`, `storage` (+ one-off `storage-init` that creates the buckets), `mailpit`. See
[architecture § 3](docs/TECHNICAL_ARCHITECTURE.md#3-services).
