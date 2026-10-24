# Xaminer

A computer-based testing platform for colleges, with automated evaluation of coding questions and
AI-assisted webcam proctoring where the AI only flags and a teacher decides.

## Status

Design phase. No application code yet — the design lives in [`docs/`](docs/):

| Document | What it covers |
|---|---|
| [PRD.md](docs/PRD.md) | Features, rules, scope |
| [TECHNICAL_ARCHITECTURE.md](docs/TECHNICAL_ARCHITECTURE.md) | Services, stack, database, API, key flows |
| [SECURITY_AND_ACCESS.md](docs/SECURITY_AND_ACCESS.md) | Permissions, sandbox, proctoring privacy, threats |
| [FRONTEND_SPEC.md](docs/FRONTEND_SPEC.md) | Pages, routes, exam screen |
| [FEATURE_TICKETS.md](docs/FEATURE_TICKETS.md) | Tickets and build order |

## Planned stack

React + Vite (frontend) · FastAPI (backend) · PostgreSQL · Redis + Celery · MinIO · Docker sandboxes for
code execution · MediaPipe (in-browser) and PyTorch/ONNX (server) for proctoring · Docker Compose.

Setup and run instructions will be added here as the project is built.
