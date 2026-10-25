# Xaminer

A computer-based testing platform for colleges, with automated evaluation of coding questions and
AI-assisted webcam proctoring where the AI only flags and a teacher decides.

## Status

Building **E00 Foundation**. Done: TCK-0001 (repository layout and code checks), TCK-0002 (Docker
Compose stack), TCK-0003 (FastAPI skeleton: settings, JSON logs, error format, request IDs, health),
TCK-0004 (database: SQLAlchemy + Alembic, `migrator`/`app` users, automatic institution filter),
TCK-0005 (language catalogue, `platform-admin` command).
Workers are still placeholders until their tickets. The design lives in
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

Database tests use the `xaminer_test` database of the running stack, so run `make up` first; without it
they are skipped (in CI, `REQUIRE_DB=1` makes them fail instead).

**Database migrations** (from `backend/`, with the stack running):

```sh
uv run alembic revision --autogenerate -m "what changed"   # then review the generated file
make up                                                      # the `migrate` service applies it
```

For `alembic` commands on the host, export `POSTGRES_HOST=127.0.0.1`, `POSTGRES_PORT=15432` and
`DB_MIGRATOR_PASSWORD` from `deploy/.env` first.

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
| http://localhost:8025 | Mailpit — emails sent in development |
| `localhost:8333` | Object storage S3 API (SeaweedFS) |
| `localhost:15432` | PostgreSQL, for local DB tools |

### Platform admin commands

Set-up tasks for whoever runs the platform (not an in-app role). The stack must be up.

```sh
make platform-admin ARGS='create-institution --name "ABC College"'   # timezone defaults to Asia/Kolkata
make platform-admin ARGS='create-institution --name "XYZ" --timezone Europe/London'
make platform-admin ARGS='list-institutions'
make platform-admin ARGS='list-languages'
```

Services: `web`, `api`, `app-worker`, `scheduler`, `exec-worker`, `sandbox-docker`, `inference-worker`,
`postgres`, `redis`, `storage` (+ one-off `storage-init` that creates the buckets), `mailpit`. See
[architecture § 3](docs/TECHNICAL_ARCHITECTURE.md#3-services).
