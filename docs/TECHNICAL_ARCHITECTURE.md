# Technical Architecture — CBT Platform with AI Proctoring and Automated Coding Evaluation

| Field | Value |
|---|---|
| Document | 2 of 5 — Technical Architecture |
| Status | Draft v0.2 — architecture, stack and services agreed; schema and API to be reviewed next |
| Last updated | 2026-10-24 |
| Code | None yet. This document comes first. |

**This document owns:** services, tech stack, module boundaries, enum values, database tables, API paths,
queues. Requirements live in `PRD.md`, permissions and threats in `SECURITY_AND_ACCESS.md`, screens in
`FRONTEND_SPEC.md`, tickets in `FEATURE_TICKETS.md`.

---

## 1. Overview

A web-based exam platform for colleges. Teachers build exams (MCQ, MSQ, True/False, descriptive, coding),
students take them in the browser, coding answers are run and graded automatically in sandboxes, and a
webcam-based proctoring system flags suspicious moments for a teacher to review.

It runs as a set of Docker containers started with one `docker compose up`.

### Design rules

These are the rules the whole design is built around. Every later section follows from them.

1. **Student code never runs in a trusted process.** It runs in a throwaway container with no network.
   The service that runs it has no database access and never computes a score.
2. **Hidden test cases never reach the browser.** Student-facing responses are built from explicit
   "student view" types, never by deleting fields from a full object.
3. **The server owns the clock.** The deadline is stored on the server; the browser countdown is only a
   display.
4. **No answer is lost.** Autosave is idempotent and versioned; the browser keeps unsent answers in
   IndexedDB until the server confirms them.
5. **AI flags, humans decide.** A proctoring event is never a penalty. Severity is set by the server, and
   only a teacher's review can mark something as a concern. Proctoring never changes a score.
6. **Published exams are frozen.** Publishing snapshots the exam and pins question versions, so any grade
   can be reproduced later.
7. **Every row belongs to an institution.** Multi-tenant from day one: `institution_id` on every domain
   table, taken from the logged-in user, never from the request body.

---

## 2. Tech stack

| Layer | Choice |
|---|---|
| Frontend | Vite + React 19 + TypeScript 5.9 (not 6: tools like `openapi-typescript` don't support it yet), React Router 7, TanStack Query, IndexedDB (plain API), Tailwind CSS 4 + shadcn/ui (Radix) |
| Code editor | CodeMirror 6 (lighter than Monaco, which matters while proctoring models also run in the browser) |
| Browser AI | MediaPipe Tasks Vision (face landmarks, head pose), a WebRTC-style voice activity detector |
| Backend API | Python 3.12, FastAPI, Pydantic v2 |
| Database access | SQLAlchemy 2 (async) + Alembic migrations |
| API types for frontend | `make api-client`: backend writes `frontend/src/api/openapi.json` → `openapi-typescript` writes `schema.d.ts` → `openapi-fetch` client. Both files are committed; a wrong path or body fails `tsc` |
| Auth | Argon2 password hashing, JWT access tokens (15 min), rotating refresh token in an httpOnly cookie |
| Background jobs | Celery + Redis, Celery Beat for scheduled jobs |
| Code sandbox | Docker containers (one per test case) on a Docker-in-Docker engine; gVisor `runsc` optional |
| Proctoring AI (server) | PyTorch / ONNX Runtime, reusing smartSquad's RT-DETR object detector and liveness code |
| Database | PostgreSQL 16 |
| Cache / broker | Redis 7 |
| File storage | SeaweedFS (S3-compatible). Code uses the plain S3 API (boto3), so the store can be swapped |
| Email | Mailpit in development, any SMTP server in production |
| Deployment | Docker Compose on one Linux machine (WSL2 on Windows for development) |
| Dev tooling | Backend: uv (Python 3.12 + dependencies + lockfile), ruff, mypy (strict), pytest. Frontend: npm, oxlint, Prettier, `tsc`. A root `Makefile` runs them all (`make check`) |
| CI | GitHub Actions: lint, type-check, tests, image build |
| Logging | Structured JSON logs; Sentry optional |

**Not used, on purpose:** Kubernetes, microservices, WebSockets (polling is enough), Elasticsearch
(Postgres full-text search is enough), Judge0 (we need control over hidden tests and scoring), any
third-party proctoring or cloud vision API (student images stay on our servers).

---

## 3. Services

Each row is one container in `docker-compose.yml`. A component gets its own container only when its
security risk, language or resource needs are different from the API's.

| Service | Role | Can reach | Must never |
|---|---|---|---|
| `web` | nginx. Serves the React build, forwards `/api/*` to `api` | `api` | Contain logic |
| `api` | FastAPI. All business logic, the only public backend | Postgres, Redis, object storage | Run student code or ML models |
| `app-worker` | Celery. Trusted background work: grading, scoring code results, saving proctoring verdicts, emails, cleanup | Postgres, Redis, object storage, SMTP | Run student code |
| `scheduler` | Celery Beat. Puts scheduled jobs on the queue (sweeper, retention) | Redis | Do the work itself |
| `exec-worker` | Celery. Runs student code: fetches test bundle, compiles, runs each case in a container, returns raw output | Redis, `sandbox-docker`, storage via pre-signed URLs only | Hold DB or storage credentials, compare output, compute scores |
| `sandbox-docker` | Docker-in-Docker engine where student containers run | Nothing (student containers have no network) | Be the host's Docker engine |
| `inference-worker` | Celery. Checks proctoring images: face count, phone/book detection, liveness | Redis, storage via pre-signed URLs only | Hold DB or storage credentials, decide outcomes |
| `postgres` | All permanent data | — | Store image files |
| `redis` | Celery broker, rate limits, idempotency keys, heartbeat cache | — | Be the only copy of anything important |
| `storage` | Evidence images, test bundles, question images | — | Be publicly readable |
| `mailpit` | Dev only: catches outgoing email | — | — |

One-off setup services run on every start and then exit: `db-init` (creates the `migrator` and `app`
database users and the test database), `migrate` (applies migrations), `storage-init` (creates buckets).

Language runner images (`cpp17`, `java21`, `python312`, `node22`) are images, not running services.
`sandbox-docker` starts containers from them on demand.

**Rule for untrusted input:** `exec-worker` (student code) and `inference-worker` (student-uploaded images)
have no database credentials. They send results back on a queue; `app-worker` checks each result against
the job record in the database before saving anything.

**About Docker-in-Docker, honestly:** it keeps student containers off the host's Docker engine, so they
cannot see or touch platform containers, and `exec-worker` never holds the host Docker socket. It is not a
strong security boundary by itself (the DinD container is privileged). The real protection is the
container profile in § 9.3; gVisor or a separate VM for `sandbox-docker` are the upgrades if needed.

### How they talk

```
browser ──HTTPS──► web ──► api ──► postgres / redis / storage
api ──enqueue──► redis ──► exec-worker ──► sandbox-docker ──► runner containers
                       └─► inference-worker
exec-worker / inference-worker ──result queue──► app-worker ──► postgres
scheduler ──► redis ──► app-worker
```

All browser updates use polling. Endpoints that change in the background return `poll_after_ms`.

### Docker networks

| Network | Members |
|---|---|
| `frontend` | `web`, `api` |
| `backend` | `api`, `app-worker`, `scheduler`, `postgres`, `redis`, `storage`, `mailpit` |
| `exec` | `exec-worker`, `sandbox-docker`, `redis`, `storage` |
| `inference` | `inference-worker`, `redis`, `storage` |

Postgres is only on `backend`, so the two untrusted-input workers cannot reach it even by address.

---

## 4. Repository layout

One repository.

```
/frontend              Vite + React app
/backend
  app/                 FastAPI app, one folder per module (§ 5)
  domain_core/         Pure functions, no I/O: output comparison, scoring, timer maths, integrity outcome
  workers/
    app_worker/        Celery tasks for app-worker and scheduler
    exec_worker/       Sandbox runner
    inference_worker/  Proctoring models (ported from smartSquad)
  alembic/             Migrations
  cli/                 platform-admin command (create institution, first admin)
/runners/<language>/   Dockerfile per language runner
/deploy                docker-compose.yml, nginx.conf, .env.example
/docs                  These five documents
```

The three workers share the backend codebase but build into separate images, so `inference-worker`
carries PyTorch and `exec-worker` carries the Docker client, and neither image gets database settings.

`domain_core` holds every rule that decides a grade. It has exactly one implementation, no I/O, and the
most unit tests in the project.

---

## 5. API modules

Folders inside `backend/app`. A module reads and writes only its own tables; it uses other modules
through their service functions.

| Module | Owns | Notes |
|---|---|---|
| `platform` | `institution`, `language` | Institutions are created with the `platform-admin` CLI, not in the UI |
| `auth` | `refresh_token`, `auth_token` | Login, refresh, logout, invitations, password reset, lockout |
| `users` | `user`, `user_group`, `user_group_member` | User CRUD, groups, CSV import |
| `authz` | — | Role table in code; routes declare `require(P.…)` or `PUBLIC`, or the app refuses to start; ownership checks |
| `questions` | `question`, `question_version`, `question_option`, `coding_config`, `test_case`, `reference_solution` | Has a separate student view that can never include hidden tests or correct answers |
| `exams` | `exam`, `exam_question`, `exam_version`, `exam_assignment` | Create, configure, publish (freeze), assign |
| `attempts` | `exam_attempt`, `attempt_question`, `answer`, `code_draft` | Start, heartbeat, autosave, submit, timer |
| `execution` | `code_run`, `coding_submission`, `coding_evaluation`, `test_case_result` | Creates jobs and shows results. Never executes code |
| `grading` | score fields on `answer` | Auto-grading, manual grading of descriptive answers |
| `results` | `result`, `result_revision` | Computes and releases results |
| `proctoring` | `consent_record`, `proctoring_event` | Event upload, review queue, integrity outcome. May not import `grading` or `results` |
| `monitoring` | — | Live exam view, analytics. Read-only |
| `notifications` | `notification` | In-app list + email jobs |
| `audit` | `audit_log` | Append-only. Every module writes to it |
| `storage` | — | Pre-signed storage URLs, upload checks, image re-encoding |

**Tenant scoping.** Every request gets `institution_id` from its JWT and opens a `tenant_session` for it.
A SQLAlchemy hook (`app/db/tenancy.py`) then adds `institution_id = …` to every ORM SELECT, UPDATE and
DELETE on tenant tables, stamps new rows with the session's institution, and refuses rows for another
institution. A query in a session with no institution raises an error instead of returning everything.
CLI commands and cross-institution jobs use an explicit `system_session`. Raw SQL is not filtered, so
it must filter by hand. (Postgres row-level security is an optional extra.)

---

## 6. Enum values

Use these exact strings everywhere: database, API, frontend.

```
Role                   ADMIN | TEACHER | STUDENT
UserStatus             INVITED | ACTIVE | DEACTIVATED
QuestionType           MCQ | MSQ | TRUE_FALSE | DESCRIPTIVE | CODING
QuestionVisibility     PRIVATE | INSTITUTION
MsqScoring             ALL_OR_NOTHING | PARTIAL
ExamStatus             DRAFT | PUBLISHED | ARCHIVED
NavigationMode         FREE | SEQUENTIAL
ResultReleasePolicy    MANUAL | ON_SUBMIT
CountedSubmission      BEST | LAST
AttemptStatus          IN_PROGRESS | SUBMITTED | AUTO_SUBMITTED | VOIDED
GradingStatus          PENDING | AWAITING_CODING | AWAITING_MANUAL | COMPLETE
TestCaseVisibility     PUBLIC | HIDDEN
ComparisonMode         EXACT | TRIM | TOKEN | NUMERIC
JobStatus              QUEUED | RUNNING | COMPLETED | FAILED
Verdict                ACCEPTED | PARTIAL | WRONG_ANSWER | COMPILE_ERROR | RUNTIME_ERROR
                       | TIME_LIMIT_EXCEEDED | MEMORY_LIMIT_EXCEEDED | INTERNAL_ERROR
TestCaseOutcome        PASSED | WRONG_ANSWER | TIMEOUT | MEMORY_LIMIT | RUNTIME_ERROR
                       | OUTPUT_LIMIT | SKIPPED
ProctoringMode         OFF | VIDEO | VIDEO_AUDIO
ProctoringEventType    FACE_ABSENT | MULTIPLE_FACES | GAZE_AWAY | PHONE_DETECTED
                       | BOOK_DETECTED | TAB_SWITCH | VOICE_DETECTED | SIGNAL_LOST
ProctoringSensitivity  RELAXED | STANDARD | STRICT
Severity               LOW | MEDIUM | HIGH
ProctoringEventStatus  PROCESSING | PENDING_REVIEW | DISMISSED | FLAGGED | REJECTED
IntegrityOutcome       PENDING_REVIEW | NO_CONCERNS | CONCERNS_CONFIRMED
```

`TAB_SWITCH` covers tab changes, window blur and leaving fullscreen; the payload says which.
`REJECTED` events (the server check found nothing) are never shown to anyone and their images are deleted.

---

## 7. Database

### 7.1 Conventions

| Topic | Rule |
|---|---|
| Primary keys | UUID (v7, generated in the app) |
| Tenancy | `institution_id NOT NULL` on every table except `institution` and `language`; part of every unique constraint |
| Time | `timestamptz`, UTC. `created_at`, `updated_at` on every table |
| Scores | `numeric(8,2)`, never float |
| Flexible data | `jsonb` only for snapshots and detector payloads |
| Enum columns | `text` + `CHECK` constraint with the § 6 values (easier to extend than Postgres enum types) |
| Constraint names | Fixed naming convention (`pk_`, `fk_`, `ix_`, `uq_`, `ck_` + table/columns) so migrations can refer to them |
| Migrations | Alembic, run by the one-off `migrate` service as `migrator` before `api` and `app-worker` start |
| Deletes | `ON DELETE RESTRICT` by default; graded work is never cascade-deleted |
| Names | `snake_case`, singular table names |

### 7.2 Tables

> Draft — this is the list we review next. Columns shown are the important ones, not every column.

**Platform and users**

| Table | Key columns | Notes |
|---|---|---|
| `institution` | name, timezone, status, evidence_retention_days (default 30), default_consent_text | The tenant |
| `language` | key (`cpp17`…), display_name, image, compile_cmd, run_cmd, source_filename, time_multiplier, enabled | Global, not per institution |
| `user` | email, full_name, role, status, password_hash, failed_logins, locked_until, roll_no | Unique `(institution_id, email)` |
| `refresh_token` | user_id, family_id, token_hash, expires_at, used_at, revoked_at | Reusing a used token revokes the whole family |
| `auth_token` | user_id, purpose (`INVITE`/`RESET`), token_hash, expires_at, used_at | Single use |
| `user_group`, `user_group_member` | name (unique, ignoring case); (group_id, user_id) | Simple student groups, e.g. "CSE-A 2026". Members are students only (not deactivated ones) |

**Questions**

| Table | Key columns | Notes |
|---|---|---|
| `question` | owner_id, type, visibility, tags `text[]`, current_version_id, archived_at | Stable identity |
| `question_version` | question_id, version_no, body, points, negative_marks, msq_scoring, max_answer_length, rubric, is_locked, created_by | Locked once used in a published exam; DB triggers block any change to a locked row or its options (and unlocking) |
| `question_option` | version_id, label, is_correct, order_index | MCQ / MSQ / TRUE_FALSE |
| `coding_config` | version_id (PK), statement, input_format, output_format, constraints, allowed_languages `jsonb` (with starter code), time_limit_ms, memory_limit_mb, comparison_mode, partial_scoring, run_code_allowed, max_submissions, bundle_key, validation_status, validation_report `jsonb` | 1:1 with a coding question version |
| `test_case` | version_id, visibility, weight, input, expected_output, order_index | Hidden cases are only read by a dedicated function that never feeds student views |
| `reference_solution` | version_id, language_key, source | Teacher's answer key, used to validate test cases |

**Exams**

| Table | Key columns | Notes |
|---|---|---|
| `exam` | owner_id, title, instructions, status, open_at, close_at, duration_min, navigation_mode, shuffle_questions, shuffle_options, run_code_enabled, release_policy, counted_submission, pass_percent, proctoring_mode, proctoring_detectors `jsonb` (sensitivity, gaze on/off, books on/off), consent_text, published_version_id | Settings live on the exam row |
| `exam_question` | exam_id, question_id, pinned_version_id, order_index, points, negative_marks | Version pinned at publish. Points and negative marks: null means the question's own. Order is unique per exam, checked at commit so a reorder can swap |
| `exam_version` | exam_id, version_no, snapshot `jsonb`, content_hash, published_at | Frozen copy of the exam at publish (settings, consent text, questions with answer keys and rubrics for grading; students only ever get the student view built from it). `content_hash` is SHA-256 of the canonical JSON. A trigger blocks any update or delete, so a published exam can't be deleted either |
| `exam_assignment` | exam_id, student_id, assigned_by, via_group_id | Unique `(exam_id, student_id)`. No assignment, no attempt |

**Attempts**

| Table | Key columns | Notes |
|---|---|---|
| `exam_attempt` | exam_id, exam_version_id, preview_snapshot `jsonb`, student_id, status, grading_status, started_at, deadline_at, submitted_at, shuffle_seed, last_heartbeat_at, extra_minutes, is_preview | Partial unique index: one non-`VOIDED` attempt per (exam, student). `is_preview` marks a teacher's test attempt, excluded from results; a preview of a draft has no published version and carries its own frozen copy in `preview_snapshot` (DB check: exactly one of the two). Checks: deadline after start, submitted attempts have `submitted_at`. Never deleted |
| `attempt_question` | attempt_id, exam_question_id, position, option_order `int[]`, marked_for_review | The order this student saw (`option_order` indexes the version's options; null when not shuffled) |
| `answer` | (attempt_id, exam_question_id) PK, selected_option_ids `uuid[]`, text_answer, client_revision, auto_score, manual_score, score, feedback, graded_by, graded_at | One row per question; upsert guarded by `client_revision`. Text ≤ 64 KB (DB check) |
| `code_draft` | (attempt_id, exam_question_id, language_key) PK, source, client_revision | Unsubmitted editor content, per language |

**Code execution**

| Table | Key columns | Notes |
|---|---|---|
| `code_run` | attempt_id, exam_question_id, language_key, source, status, compile_output, results `jsonb` | "Run Code" against public cases only. Never graded. Deleted after 24 h |
| `coding_submission` | attempt_id, exam_question_id, submission_no, language_key, source, status, is_counted | Official, graded. Unique `(attempt_id, exam_question_id, submission_no)` |
| `coding_evaluation` | submission_id, evaluation_no, verdict, passed_weight, total_weight, score, max_score, compile_output, image_digest, evaluated_at | A re-evaluation adds a new row |
| `test_case_result` | evaluation_id, test_case_id, outcome, time_ms, memory_kb, stdout (truncated), stderr (truncated) | Powers per-test-case pass rates |

`code_run` and `coding_submission` are separate tables on purpose: different rules, different lifetimes,
and mixing them is how hidden tests leak or debug runs get graded.

**Results**

| Table | Key columns | Notes |
|---|---|---|
| `result` | attempt_id (PK), total_score, max_score, percentage, passed, per_question `jsonb`, integrity_outcome, released_at | Score and integrity outcome are separate columns and never combined |
| `result_revision` | attempt_id, old_score, new_score, reason, changed_by | Only written when a released result changes |

**Proctoring**

| Table | Key columns | Notes |
|---|---|---|
| `consent_record` | exam_id, student_id, consent_text_hash, decision, decided_at | New row per decision |
| `proctoring_event` | attempt_id, event_type, started_at, ended_at, status, severity, confidence, client_payload `jsonb`, evidence_keys `text[]`, retention_until, evidence_deleted_at, review_decision, reviewed_by, reviewed_at, review_note | Check constraint: a review decision requires `reviewed_by`. Severity is null until the server sets it |

**Cross-cutting**

| Table | Key columns | Notes |
|---|---|---|
| `audit_log` | actor_id, actor_role, action, target_type, target_id, changes `jsonb`, ip, user_agent, request_id, created_at | App DB user has INSERT/SELECT only, no UPDATE/DELETE/TRUNCATE. **No foreign keys** (the log must outlive what it describes and never block a deletion); still filtered by institution |
| `notification` | user_id, type, title, body, link, read_at | In-app list |

---

## 8. API

REST + JSON under `/api/v1`.

| Topic | Rule |
|---|---|
| Auth | `Authorization: Bearer <access token>`; refresh token in the `xaminer_refresh` cookie (httpOnly, path `/api/v1/auth`). Proctoring uploads use a short-lived **attempt token** |
| Login across institutions | Login sends email + password (+ optional `institution_id`). If the same email and password match accounts in several institutions, the API answers `409 INSTITUTION_REQUIRED` with the institutions to choose from (only after a correct password), and the client repeats the login with `institution_id` |
| Tenancy | Never sent by the client; always taken from the token |
| IDs | UUIDs in paths |
| Lists | Cursor pagination: `?limit=&cursor=` → `{data, next_cursor}` |
| Idempotency | `Idempotency-Key` header required on: start attempt, autosave, submit attempt, run code, submit code |
| Errors | `{"error": {"code": "SNAKE_CASE_CODE", "message": "...", "details": [...], "request_id": "..."}}`. `details` only for validation errors (`field`, `message`). Clients check `code`, not `message`. Unexpected errors return `INTERNAL_ERROR` with no internals |
| Request ID | `X-Request-ID` accepted from the caller (if safe: ≤ 64 chars of `A-Z a-z 0-9 . _ -`) or generated; returned on every response and written on every log line |
| API docs | `/api/v1/docs` (hidden when `ENVIRONMENT=production`); spec at `/api/v1/openapi.json` |
| Not found vs forbidden | Another tenant's or another user's resource returns `404`, so its existence is not revealed |
| Time | Attempt responses include `server_time` |

Main error codes: `UNAUTHENTICATED`, `INVALID_CREDENTIALS`, `ACCOUNT_LOCKED`, `INSTITUTION_REQUIRED`, `INVALID_TOKEN`, `TOKEN_REUSE_DETECTED`, `TOKEN_ALREADY_ROTATED`, `FORBIDDEN`, `NOT_FOUND`,
`NOT_ASSIGNED`, `VALIDATION_FAILED`, `ATTEMPT_NOT_ACTIVE`, `EXAM_NOT_OPEN`, `ATTEMPT_LIMIT_REACHED`,
`CONSENT_REQUIRED`, `PUBLISH_BLOCKED`, `SUBMISSION_LIMIT_REACHED`, `RUN_CODE_DISABLED`, `RATE_LIMITED`.

### Endpoints

> Draft — reviewed together with the tables.

| Area | Endpoints | Who |
|---|---|---|
| Auth | `POST /auth/login` · `/auth/refresh` · `/auth/logout` · `/auth/logout-all` · `/auth/invite/inspect` · `/auth/invite/accept` · `/auth/password-reset/request` · `/auth/password-reset/confirm` · `GET /auth/me` | all |
| Users | `GET/POST /users` (list: `role`, `status`, `q`, `cursor`) · `GET/PATCH /users/{id}` · `POST /users/{id}/deactivate`, `/reactivate`, `/resend-invite`, `/password-reset`, `/unlock` · `POST /users/import` (the CSV's text as JSON; `dry_run: true` previews, `false` imports) · `GET/POST /groups` · `GET/PATCH/DELETE /groups/{id}` · `POST /groups/{id}/members` · `DELETE /groups/{id}/members/{user_id}` | Admin (teachers can read groups) |
| Audit, settings | `GET /audit-logs` (filters: `actor_id`, `action` exact or prefix like `user.`, `target_type`, `target_id`, `from`, `to`; cursor pages) · `GET /audit-logs/actions` · `GET/PATCH /institution/settings` (retention days, default consent text; the overdue-deletion count is added with the retention job, TCK-1107) · `GET /admin/exams` (metadata only) | Admin |
| Questions | `GET/POST /questions` (filters: `q`, `type`, `tag`, `owner` mine/shared/all, `archived`) · `GET/PATCH /questions/{id}` (text as stored plus `image_urls`, signed links for its images; PATCH on a locked version makes a new one; header `X-New-Version`) · `POST /questions/{id}/copy` · `POST /questions/{id}/archive`, `/restore` · `GET /questions/{id}/preview` (student view) · `POST /uploads/images` (multipart; returns the `ref` for Markdown and an hour-long preview link) | Teacher |
| Coding | `PUT /questions/{id}/coding` · `GET/POST /questions/{id}/test-cases` · `PATCH/DELETE /questions/{id}/test-cases/{caseId}` · `PUT /questions/{id}/reference-solutions/{lang}` · `POST /questions/{id}/validate` · `GET /languages` | Teacher |
| Exams | `GET/POST /exams` (own; filters `status`, `q`) · `GET/PATCH/DELETE /exams/{id}` (DELETE drafts only; after publish PATCH may change only `close_at`, else 409 `EXAM_PUBLISHED` naming the field) · `GET/PUT /exams/{id}/questions` (PUT replaces the whole ordered list in one transaction; drafts only; own or institution-shared, non-archived questions) · `GET/POST /exams/{id}/assignments` (POST: `group_ids` and/or `student_ids`; groups expand to one row per student, deactivated skipped, duplicates ignored) · `DELETE /exams/{id}/assignments/{student_id}` · `GET /exams/{id}/student-choices` (picker) · `GET /exams/{id}/publish-check` (`can_publish`, `blocks`, `warnings`; each issue has a code, a message naming what to fix, and the field or question) · `POST /exams/{id}/publish` (409 `PUBLISH_BLOCKED` listing each block; pins and locks question versions in one transaction) · `POST /exams/{id}/archive` · `POST /exams/{id}/preview-attempt` (draft or published; replaces the previous preview) | Teacher |
| Student exams | `GET /student/exams` (`available`, `upcoming`, `completed`; each with a state: AVAILABLE, IN_PROGRESS, TOO_LATE, UPCOMING, SUBMITTED, MISSED) · `GET /student/exams/{id}` (instructions page, with `server_time`) · `POST /student/exams/{id}/consent` · `POST /student/exams/{id}/attempts` (start; safe to repeat; 409 `EXAM_NOT_OPEN`, `EXAM_CLOSED`, `TOO_LATE_TO_START`, `ALREADY_SUBMITTED`) | Student |
| Attempt | `GET /attempts/{id}` (resume: the same payload as start) · `POST /attempts/{id}/heartbeat` (status, deadline, server time, fresh attempt token; live data in Redis, `last_heartbeat_at` written at most once a minute) · `PUT /attempts/{id}/answers` (batch; each with `client_revision`, only newer ones stored, older listed as `stale`; 409 `TIME_UP` after deadline + 60 s) · `PUT /attempts/{id}/flags/{eqId}` · `PUT /attempts/{id}/drafts/{eqId}` · `POST /attempts/{id}/submit` (receipt; repeating returns the same one; after the deadline it counts as automatic, since the exam screen submits by itself at zero) · `GET /attempts/{id}/receipt` | Student (own) |
| Code | `POST /attempts/{id}/questions/{eqId}/runs` · `GET /runs/{runId}` · `POST /attempts/{id}/questions/{eqId}/submissions` · `GET /submissions/{id}` · `GET /attempts/{id}/questions/{eqId}/submissions` | Student (own), Teacher |
| Proctoring upload | `POST /attempts/{id}/proctoring/events` · `POST /attempts/{id}/proctoring/spot-checks` | Attempt token |
| Monitoring | `GET /exams/{id}/monitor` · `POST /attempts/{id}/extend` (minutes + reason; never past the window's end: 409 `WINDOW_ENDS_FIRST`; at most 600 extra) · `POST /attempts/{id}/force-submit` · `POST /attempts/{id}/void` (any non-voided attempt; the student may restart). All need a reason, kept in the audit log | Teacher |
| Grading | `GET /exams/{id}/grading` · `PUT /attempts/{id}/answers/{eqId}/mark` · `POST /exams/{id}/re-evaluate` | Teacher |
| Results | `GET /exams/{id}/results` · `POST /exams/{id}/results/release` · `GET /exams/{id}/analytics` · `GET /student/results` · `GET /student/results/{attemptId}` | Teacher / Student (released only) |
| Review | `GET /exams/{id}/proctoring/events` · `GET /attempts/{id}/proctoring/timeline` · `GET /proctoring/events/{id}/evidence` (5-min signed URL) · `PUT /proctoring/events/{id}/review` | Teacher |
| Notifications | `GET /notifications` · `POST /notifications/{id}/read` | all |
| Health | `GET /health` | — |

---

## 9. Key flows

### 9.1 Exam attempt

| Step | What happens |
|---|---|
| Start | Checks: exam published, window open (server time) with ≥ 5 min left, student assigned, no existing non-voided attempt, consent given if proctored. Creates `exam_attempt` with `deadline_at = min(now + duration + extra, close_at)` and the shuffled `attempt_question` order. Two simultaneous starts: the partial unique index lets one win; the other returns the winner's attempt |
| Timer | Every response carries `server_time`. The browser computes `offset = server_time − local_time` and shows `deadline_at − (local_time + offset)`. The browser clock is never trusted |
| Autosave | Browser saves to IndexedDB first, then sends all changed answers in one batch `PUT /attempts/{id}/answers` every 2–3 s, each with its `client_revision`. Server upserts each: `INSERT … ON CONFLICT DO UPDATE … WHERE answer.client_revision < new.client_revision`. Old or repeated writes are harmless |
| Heartbeat | Every 15 s. Returns remaining time, any teacher action (time extended, force-submitted), and a fresh attempt token. Stored in Redis, written to Postgres at most once a minute |
| Offline | Browser keeps working and retries with backoff; queued answers are sent when the connection returns |
| Submit | `UPDATE exam_attempt SET status='SUBMITTED' WHERE id=? AND status='IN_PROGRESS'`. Zero rows = already submitted → return the existing receipt. Grading is queued, not done inline |
| Deadline | Every write is rejected after `deadline_at + 60 s grace`. The scheduler's sweeper auto-submits overdue attempts every 30 s, and any request touching an overdue attempt submits it first |
| Unsubmitted code | When an attempt ends, any coding question whose last saved draft is newer than its last submission (or has no submission) gets that draft submitted and graded automatically. It does not count against the submission limit |

Attempt status, grading status and release are three separate fields: `status`, `grading_status`,
`result.released_at`.

```
IN_PROGRESS → SUBMITTED | AUTO_SUBMITTED → (VOIDED by teacher, with reason)
grading: PENDING → AWAITING_CODING → AWAITING_MANUAL → COMPLETE
```

### 9.2 Code execution

```
Student clicks Run / Submit
  → api: check limits, save draft, create code_run or coding_submission (QUEUED),
         enqueue job {job_id, language, limits, source, bundle_url (pre-signed, 5 min)}
  → exec-worker: download bundle, check its hash
         compile once (if needed) in a container
         for each test case: new container, feed input, capture stdout/stderr/time/memory, destroy
         send raw results to the result queue
  → app-worker: check job exists and is RUNNING, compare outputs (domain_core),
         compute score (domain_core), save evaluation + test_case_results,
         update grading_status
  → browser polls GET /runs/{id} or /submissions/{id}
```

| Queue | Used for | Notes |
|---|---|---|
| `exec.validation` | Teacher validating test cases with a reference solution | Runs all cases |
| `exec.run` | Run Code | Public cases only. Rate limit: 1 per 8 s per student, max 20 per question |
| `exec.submit` | Submit Code | All graded cases. Always accepted, never dropped |
| `exec.results` | Raw results back to `app-worker` | — |

If Run Code becomes slow under load, start a second `exec-worker` that listens only to `exec.run`.

**Test bundle.** When a coding question version is saved, `app-worker` builds one tar file
(`001.in`, `001.out`, …, `manifest.json`) and stores it in object storage. The worker gets a pre-signed URL for that
one file only. Bundles never change, so the worker can cache them by hash.

**Scoring rules** (in `domain_core`):
- Compile error → 0.
- Partial scoring on → `points × passed_weight ÷ total_weight`, rounded to 2 decimals.
- Partial scoring off → full points only if every graded case passes.
- Infrastructure failure → no score; status `FAILED`, verdict `INTERNAL_ERROR`; teacher can re-evaluate.
  *A student's program failing is a grade. The platform failing is never a grade.*
- Counted submission per question: `BEST` or `LAST`, set on the exam.

### 9.3 Sandbox profile

Every test case runs in a fresh container started like this:

| Control | Setting |
|---|---|
| Network | `--network none` |
| Filesystem | `--read-only`, plus `--tmpfs /work:size=64m` |
| User | Non-root (`--user 10001`) |
| Privileges | `--cap-drop ALL`, `--security-opt no-new-privileges`, default seccomp |
| Memory | `--memory` = limit, `--memory-swap` = same (no swap) |
| CPU | `--cpus 1`, plus a wall-clock kill at 2× the time limit |
| Processes | `--pids-limit 64` (stops fork bombs) |
| Output | Read at most 64 KB of stdout; more → `OUTPUT_LIMIT` |
| Lifetime | Container removed after the case; worker checks it is gone |
| Optional | `--runtime runsc` (gVisor) when available |

Hidden test cases only exist inside the bundle, the worker's temp folder and the database. They are never
in a browser response; a test seeds hidden cases with unique strings and checks no student endpoint returns
them.

### 9.4 Proctoring

**In the browser** (nothing is streamed or recorded):

| Detector | How | Event |
|---|---|---|
| No face | MediaPipe, 2–4 fps, for > N seconds | `FACE_ABSENT` |
| More than one face | MediaPipe | `MULTIPLE_FACES` |
| Looking away | MediaPipe head pose, for > N seconds (off by default) | `GAZE_AWAY` |
| Tab / window / fullscreen | Browser events | `TAB_SWITCH` |
| Talking | Voice activity detection, `VIDEO_AUDIO` mode only; no audio is uploaded | `VOICE_DETECTED` |

**On the server:**

| Detector | How | Event |
|---|---|---|
| Phone / book | Random spot-check frame every 20–40 s → RT-DETR on `inference-worker` | `PHONE_DETECTED`, `BOOK_DETECTED` (off by default) |
| Proctoring stopped | Heartbeats keep arriving but the browser's proctoring counter has stopped for > 60 s. If heartbeats stop too, it is a network problem, not this event (§ 9.6) | `SIGNAL_LOST` |

**Event flow:**

```
Camera event in browser → upload {event info, up to 3 JPEG frames} with attempt token
  → api: check type & size, re-encode images (removes EXIF/GPS), store at tmp/ in object storage,
         save event as PROCESSING (no severity), enqueue check
  → inference-worker: re-check the frames → CONFIRM or REJECT, with severity + confidence
  → app-worker: CONFIRM → move images to evidence/, status PENDING_REVIEW
                REJECT  → delete images, status REJECTED (never shown)

Spot-check frame → tmp/ → inference-worker → finding? create event with this frame as evidence
                                           : delete the frame within minutes

TAB_SWITCH, VOICE_DETECTED, SIGNAL_LOST (no images) → api sets severity by fixed rules → PENDING_REVIEW
```

The upload response never contains severity or verdicts, so a student cannot use it to test what gets
detected.

**Review.** After an attempt ends, the teacher sees its events, opens evidence through a
5-minute signed URL (logged in the audit log), and marks each event `DISMISSED` or `FLAGGED` with a note.
The attempt's integrity outcome is computed from these decisions only:

| Decisions | Outcome |
|---|---|
| Any event still `PENDING_REVIEW` | `PENDING_REVIEW` |
| All dismissed, or no events | `NO_CONCERNS` |
| At least one flagged | `CONCERNS_CONFIRMED` |

The outcome is shown next to the score, never mixed into it. Students never see events, severity or
confidence.

**Retention.** Evidence images are deleted `evidence_retention_days` (default 30) after the exam closes by
a scheduled job. Event rows (without images) are kept with the result.

**Consent and device check.** Before a proctored exam the student reads the consent text and accepts, then
the browser checks camera (and mic for `VIDEO_AUDIO`), shows a self-view, and confirms the models loaded.
Declining consent means the student cannot start that exam.

### 9.5 Grading and results

1. On submit, `app-worker` grades objective answers (MCQ exact; MSQ all-or-nothing or partial; negative
   marks if set).
2. Coding scores arrive as evaluations finish.
3. Descriptive answers appear in the teacher's grading queue, grouped by question.
4. When nothing is pending, `grading_status = COMPLETE` and the `result` row is computed.
5. Teacher releases results (or they release on submit, if the exam has no descriptive questions).
6. Changing a released score writes a `result_revision` and notifies the student.

### 9.6 Weak or lost connections

The exam must keep working on a bad connection, never lose an answer, and never treat a bad connection
as cheating.

| Area | Rule |
|---|---|
| Before the exam | The device-check page downloads and caches (Service Worker) the MediaPipe models, WASM files and editor modes, and measures latency and speed. A weak result shows a warning; it does not block |
| At start | One response carries all questions. Question images are fetched right after. From then on the exam only needs the network to save |
| Upload order | One uploader in the browser sends, in priority order: answers and code drafts → heartbeat → Run/Submit Code → proctoring events → spot checks. On a slow link spot checks are skipped and evidence waits |
| Requests | 10 s timeout, retry with jittered backoff (1 s → 30 s), idempotency keys, gzip and HTTP/2 at nginx |
| Timer | Keeps running while offline. The deadline does not move. The teacher sees disconnection time on the monitor and can extend the attempt |
| Late answers | Rejected after `deadline + 60 s grace`. The student is told honestly which offline changes were not saved |
| Unsubmitted code | Last saved draft is auto-submitted at the end (§ 9.1) |
| Evidence upload | The attempt token stays valid for proctoring uploads for 30 min after the attempt ends, so queued evidence can finish uploading later |
| Not cheating | A heartbeat gap is logged as a connection gap on the attempt timeline and monitor, never as a proctoring event |
| Student UI | Status always visible: *All saved* / *Saving…* / *Offline — N answers saved on this device*. The student is never blocked from working |
| Teacher monitor | Each student shows *online* (heartbeat < 30 s), *weak* (30–90 s) or *offline* (> 90 s), plus answers waiting to sync, reported in the heartbeat |

---

## 10. Background jobs

| Job | Runs on | When |
|---|---|---|
| Grade objective answers | app-worker | On attempt submit |
| Save code results + score | app-worker | Result arrives on `exec.results` |
| Save proctoring verdict | app-worker | Result arrives from inference-worker |
| Build test bundle | app-worker | Coding question version saved |
| Send email | app-worker | Invitations, password reset, results released |
| Auto-submit sweeper | app-worker, via scheduler | Every 30 s |
| Stuck job retry | app-worker, via scheduler | Every 5 min: re-queue runs/submissions stuck in `QUEUED`/`RUNNING` |
| Evidence cleanup | app-worker, via scheduler | Hourly: delete expired evidence and old spot-check frames |
| Code run cleanup | app-worker, via scheduler | Daily: delete `code_run` rows older than 24 h |

Every job is safe to run twice: it checks the current state (by job id, attempt id or event id) before
changing anything, because Celery may deliver a job more than once.

**Celery setup** (`backend/workers/`):

| Topic | Rule |
|---|---|
| Queue names | Defined once in `workers/queues.py`. `app-worker` consumes `default`, `grading`, `exec.results`, `inference.results`, `maintenance`, `notify`; `exec-worker` consumes `exec.validation`, `exec.submit`, `exec.run`; `inference-worker` consumes `inference.verify` |
| Sending | The API sends tasks **by name** (`send_task`), so it never imports worker code |
| Format | JSON only, never pickle (untrusted workers share Redis, and pickle can run code) |
| Delivery | Acknowledged after the task finishes; a crashed worker's job is redelivered |
| Logging | Task arguments and return values are never logged (they will carry answers and code) |
| Scheduler | Exactly one `scheduler` (Celery Beat). Schedules live in `workers/app_worker/__init__.py` |

---

## 11. Deployment

- **Development:** `make up` (Docker Desktop, WSL 2 engine) using `deploy/docker-compose.yml`. App at
  `localhost:8080`, Mailpit at `localhost:8025`, S3 API at `localhost:8333`, Redis at `localhost:16379`
  (tests use its database 15), Postgres at `localhost:15432`
  (avoids a locally installed Postgres). A one-off `storage-init` service creates the buckets `evidence`,
  `bundles`, `images`. The inference worker can run with a lightweight stub model on machines without a GPU.
- **Demo / college server:** the same Compose file on one Linux machine, with real SMTP settings and HTTPS
  at nginx.
- **Setup:** migrations run automatically on `make up`. Then
  `make create-institution NAME="ABC College"` (default timezone `Asia/Kolkata`) and
  `make create-admin INSTITUTION="ABC College" EMAIL=... NAME="..."` (hidden password prompt) create
  the first institution and its admin.
  `platform-admin` is `python -m cli` inside the `api` image, connecting as the `app` DB user.
- **Config:** all settings and secrets in `.env` (never committed); `.env.example` lists them.
- **Backups:** Postgres holds all state, so it is the one thing that must not be lost. A nightly `pg_dump`
  plus a copy of the Storage buckets, kept for 7 days, with the restore steps written down and tried once.
  Redis is not backed up (nothing permanent lives there).
- **CI:** on every push — lint (ruff, oxlint, Prettier), type-check (mypy, tsc), unit tests (including `domain_core`),
  API tests against a real Postgres, and the hidden-test-case leak test. Sandbox tests run on a Linux
  runner with Docker.

---

## 12. Decisions

Short records of the choices most likely to be questioned.

| # | Decision | Why |
|---|---|---|
| D-01 | One API app with modules, plus separate workers | The data is tightly linked (attempts, answers, results); splitting the API into microservices adds network calls and sync problems for no gain. Workers are split out only where security or resources differ |
| D-02 | FastAPI (Python) backend | Team knows Python; API, workers and AI share one language. Typed frontend client is generated from OpenAPI |
| D-03 | Vite + React SPA, not Next.js | No SEO or server rendering needed; a static build behind nginx is simpler |
| D-04 | Our own code runner, not Judge0 | We need control over hidden tests, weighted scoring and comparison rules. The hard part is the container profile, which is configuration |
| D-05 | Workers that handle untrusted input have no DB access | A compromised worker can at most lie about one job's output; it cannot read other students' data |
| D-06 | Scoring only in `domain_core`, called by app-worker | One implementation for Run, Submit and validation; easy to unit-test; grades can be recomputed |
| D-07 | Browser-side detection + server re-check | No video leaves the device; server traffic scales with events, not exam length; the student's device never decides severity |
| D-08 | Build proctoring ourselves | Commercial tools record video and produce risk scores, the opposite of our "flag, then human decides" approach. Student images stay on our server |
| D-09 | Polling, not WebSockets | Needed freshness is 1–15 s; polling is simpler and has no connection state |
| D-10 | Multi-tenant from the start | Adding `institution_id` later means touching every table and query |
| D-11 | Immutable versions + DB triggers | A grade must be explainable after the question or exam is edited |
| D-12 | Uploads go through the API, not straight to object storage | The API must check file type, size and strip EXIF before storing |
| D-13 | Postgres for everything durable, incl. search | One database to run; full-text search covers the question bank |
| D-14 | SeaweedFS instead of MinIO (changed 2026-10-25) | MinIO stopped publishing free images in Oct 2025 and archived its community edition in 2026. SeaweedFS is Apache-licensed, runs as one container, and supports S3 auth, private buckets and pre-signed URLs (all verified). We only use the S3 API, so the store stays swappable |
