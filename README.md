# Xaminer

[![CI](https://github.com/Athreez/xaminer/actions/workflows/ci.yml/badge.svg)](https://github.com/Athreez/xaminer/actions/workflows/ci.yml)

A computer-based testing platform for colleges, with automated evaluation of coding questions and
AI-assisted webcam proctoring where the AI only flags and a teacher decides.

## Status

| Epic | Progress |
|---|---|
| E00 Foundation | ✅ Done: repo layout and checks, Docker Compose stack, FastAPI skeleton, database layer with automatic institution filter, language catalogue and `platform-admin`, Celery workers, frontend skeleton with typed API client, CI |
| E01 Authentication | ✅ Done: user and token tables, password hashing and rules, `create-admin` (TCK-0101, 0102); login, logout, logout everywhere, `/auth/me` API (TCK-0103); refresh-token rotation with theft detection (TCK-0104); invitations and password reset with emails (TCK-0105, 0201); account lockout and login rate limit (TCK-0106); permission system, every route must declare access (TCK-0107); ownership checks with 404 for anything not yours (TCK-0108); append-only audit log (TCK-0109); login, activation and password-reset pages with role-based routing (TCK-0110) |

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
| Backend | ruff, mypy, pytest against real Postgres and Redis (`REQUIRE_SERVICES=1`: nothing is skipped) |
| Frontend | oxlint, Prettier, type check, production build, and that `make api-client` output is committed |
| Docker images | every service image builds |

## Running the full stack

```sh
cp deploy/.env.example deploy/.env    # then change every "change-me" value
make up                               # build and start all services
make ps                               # status
make logs                             # follow logs
make down                             # stop (data volumes are kept)
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
