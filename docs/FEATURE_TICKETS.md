# Feature Tickets — CBT Platform with AI Proctoring and Automated Coding Evaluation

| Field | Value |
|---|---|
| Document | 5 of 5 — Tickets and Build Order |
| Status | Draft v0.2 — under review |
| Last updated | 2026-10-24 |
| Code | None yet. This backlog creates it. |

**This document owns:** ticket IDs, epics, build order and milestones. Each ticket points to the PRD
requirement IDs it delivers; the PRD, architecture, security and frontend docs hold the details.

---

## How to read this

Each epic is a table. Columns:

| Column | Meaning |
|---|---|
| **ID** | `TCK-EENN` (epic number + sequence). IDs are never reused |
| **Ticket** | What to build |
| **Done when** | How we check it's finished |
| **Area** | BE (backend) · FE (frontend) · DB · INF (infra/DevOps) · AI · QA |
| **Size** | S ≤ 1 day · M 2–3 days · L 4–6 days |
| **Needs** | Tickets that must be finished first |
| **P** | M = must have · S = should have (PRD § 8) |
| **PRD** | Requirement IDs delivered |

Rules for every ticket:
- Backend code has tests; API endpoints include "not allowed" tests (wrong role, wrong owner).
- Every new route declares its permission (`SECURITY_AND_ACCESS.md` § 3).
- Every state change that PRD AUD-02 lists writes an audit row.
- Student-facing responses use student view types only.

---

## Milestones

| Milestone | What works at the end | Epics |
|---|---|---|
| **M1 — Foundation** | Everything starts with `docker compose up`; admin, teacher and student can log in; admin manages users and groups | E01–E03 |
| **M2 — Objective exam end-to-end** | Teacher builds an MCQ/MSQ/TF/descriptive exam, publishes it; student takes it with autosave, resume and auto-submit; it is graded and released | E04, E05, E06, E09 (objective part) |
| **M3 — Coding end-to-end** | Coding questions with hidden tests and validation; students Run and Submit in four languages; scores in results | E07, E08, E09 (coding part) |
| **M4 — Proctoring end-to-end** | Consent, pre-check, in-browser detectors, server check, teacher review, integrity outcome, evidence deletion | E10, E11 |
| **M5 — Should-haves, quality, demo** | Monitor, analytics, notifications, security/load tests, calibration, demo deployment | E12–E14 |

### Suggested team tracks

After M1, four people (or pairs) can work mostly in parallel:

| Track | Owns |
|---|---|
| Backend core | E04, E05, E06 (API), E09 |
| Frontend | All FE tickets, especially the exam screen (E06) |
| Execution & infra | E00, E08, deployment, sandbox tests |
| AI & proctoring | E10, E11 (inference worker), calibration |

---

## E00 · Foundation

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-0001 | Repository layout per architecture § 4; uv, ruff, mypy, oxlint, Prettier, pre-commit, `Makefile`, `.gitattributes` (LF) | `make check` passes on empty projects | INF | S | — | M | NFR-14 |
| TCK-0002 | `docker-compose.yml` with all services (§ 3), networks (`frontend`, `backend`, `exec`, `inference`), `.env.example` | `docker compose up` starts everything; Postgres not reachable from the `exec` network | INF | M | 0001 | M | NFR-03 |
| TCK-0003 | FastAPI skeleton: settings, structured JSON logging, error format, `/health`, request ID | `/health` returns OK through nginx | BE | S | 0002 | M | — |
| TCK-0004 | SQLAlchemy + Alembic setup; `migrator` and `app` DB users (`db-init`, `migrate` services); base model (UUIDv7, timestamps, `institution_id`); automatic tenant filter; `institution` table (moved here from 0005, the filter needs it) | Migration runs; a query through the helper always filters by institution (test) | DB | M | 0003 | M | ACC-02 |
| TCK-0005 | `language` table seeded by migration (C++17, Java 21, Python 3.12, Node 22, with time multipliers); `platform-admin` CLI: create/list institutions, list languages | CLI creates an institution; languages listed | BE | S | 0004 | M | — |
| TCK-0006 | Celery app, `app-worker` and `scheduler` containers, a test task end-to-end | A task enqueued by the API runs on `app-worker` | BE | S | 0002 | M | — |
| TCK-0007 | Frontend skeleton: Vite, React Router, Tailwind, shadcn/ui, TanStack Query, generated API client script, layout shells per role | App builds; generated client compiles from the API's OpenAPI | FE | M | 0003 | M | — |
| TCK-0008 | GitHub Actions CI: lint, type-check, backend tests with real Postgres/Redis, frontend tests, image builds | CI green on main | INF | M | 0001 | M | NFR-14 |

## E01 · Authentication and access

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-0101 | `user`, `refresh_token`, `auth_token` tables; `platform-admin create-admin` (first admin of an institution, moved here from 0005) | Migrations applied; unique `(institution_id, email)`; CLI creates an admin | DB | S | 0005 | M | USR-01 |
| TCK-0102 | Argon2 hashing, password policy (≥ 10 chars, common-password list). **Done together with TCK-0101** (`create-admin` needed it) | Weak passwords rejected; hashes verify | BE | S | 0101 | M | AUTH-07 |
| TCK-0103 | Login, logout, logout-everywhere; JWT access token; refresh cookie | Same error for wrong email and wrong password; logout revokes | BE | M | 0102 | M | AUTH-01, AUTH-04 |
| TCK-0104 | Refresh rotation with reuse detection (family revocation) | Re-using an old refresh token logs out the whole family (test) | BE | S | 0103 | M | AUTH-03 |
| TCK-0105 | Invitation accept and password reset flows (tokens hashed, single-use, expiry) | Token works once; expired token fails; reset revokes sessions | BE | M | 0103 | M | AUTH-02, AUTH-05 |
| TCK-0106 | Redis rate limiter + account lockout | 5 failures lock 15 min; `429` with `Retry-After` | BE | S | 0103 | M | AUTH-06 |
| TCK-0107 | Permission registry; route decorator; **startup fails if a route has no permission** | Test enumerates all routes; app refuses to start with an undeclared route | BE | M | 0103 | M | ACC-01 |
| TCK-0108 | Ownership checks helper (load then check, `404` on not-yours) | Wrong-owner and wrong-institution requests return `404` (generated test) | BE | M | 0107 | M | ACC-02, ACC-03, ACC-05 |
| TCK-0109 | `audit_log` table + `audit.record()` in the same transaction; DB grant INSERT/SELECT only | `app` user can't UPDATE/DELETE audit rows (test) | BE | S | 0004 | M | AUD-01 |
| TCK-0110 | Frontend: login, activate, forgot/reset password pages; token in memory; refresh-on-401; role route guards; `/403`, `/404` | Each role lands on its home; wrong role sees `/403` | FE | M | 0007, 0105 | M | AUTH-01..05 |

## E02 · Email

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-0201 | Email sender (SMTP; Mailpit in dev) as an `app-worker` task; HTML + text templates. **Done together with TCK-0105** (plus `platform-admin invite-user` until the admin UI exists) | Invitation and reset emails arrive in Mailpit | BE | S | 0006, 0105 | M | NOT-01 |

## E03 · Users, groups, admin

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-0301 | User APIs: list/filter, create (sends invite), edit, deactivate, resend invite, send reset | Role/email change and deactivation revoke sessions; audit rows written | BE | M | 0108, 0201 | M | USR-01, USR-04 |
| TCK-0302 | Groups: tables + APIs | Add/remove members; teachers can read groups | BE | S | 0301 | M | USR-02 |
| TCK-0303 | Institution settings API (retention days, default consent text) | Values validated (7–90) and audited | BE | S | 0108 | M | PRC-13 |
| TCK-0304 | Audit log API with filters | Filter by user, action, item, date | BE | S | 0109 | M | AUD-03 |
| TCK-0305 | Admin UI: users, groups, settings, audit log, exam list | All pages per frontend § 5.1 with empty/error states | FE | L | 0110, 0301–0304 | M | USR-01..04, AUD-03 |
| TCK-0306 | CSV import: preview with row errors, then import | 2,000-row file imports; bad rows reported; duplicates skipped | Full | M | 0301 | S | USR-03 |

**✅ M1 complete**

## E04 · Question bank

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-0401 | `question`, `question_version`, `question_option` tables; **trigger blocks edits to locked versions** | Updating a locked version fails at DB level (test) | DB | M | 0004 | M | QB-07 |
| TCK-0402 | Question APIs: create, edit (new version if locked), copy, archive, list/search (full-text, type, tag, owner) | Editing a used question creates version 2; old exams keep version 1 | BE | L | 0401, 0108 | M | QB-01, QB-07, QB-09 |
| TCK-0403 | Type rules: MCQ (1 correct, 2–10 options), MSQ (≥ 1 correct, scoring mode), True/False, Descriptive (max length, rubric) | Invalid shapes rejected with field errors | BE | M | 0402 | M | QB-02..05 |
| TCK-0404 | Visibility (private / institution) and read-only access for other teachers | Other teacher can view and copy a shared question, not edit | BE | S | 0402 | M | ACC-04 |
| TCK-0405 | Markdown sanitiser (server, on save) + shared `MarkdownView` (client) | Script/iframe/event-handler payloads removed (test list) | Full | M | 0402, 0007 | M | QB-06 |
| TCK-0406 | Image upload: content check, re-encode, storage `images` bucket, signed URLs | Non-images rejected; EXIF removed | BE | M | 0402 | M | QB-06 |
| TCK-0407 | Student view types for questions (no keys, no rubric) + preview endpoint | Preview response contains no `is_correct` or rubric (test) | BE | S | 0403 | M | QB-08 |
| TCK-0408 | UI: question bank list, editor for all non-coding types, preview | Teacher creates each type and sees the student preview | FE | L | 0110, 0402–0407 | M | QB-01..09 |

## E05 · Exams

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-0501 | `exam`, `exam_question`, `exam_version`, `exam_assignment` tables; version immutability trigger | Migration applied; trigger tested | DB | M | 0401 | M | EX-06 |
| TCK-0502 | Exam APIs: create, edit, delete (no attempts), archive; settings with validation | Settings validated per PRD § 6.3 | BE | M | 0501, 0108 | M | EX-01, EX-03, EX-08 |
| TCK-0503 | Composition API: add/remove/reorder questions, points, negative marks | Reorder is atomic; totals correct | BE | S | 0502 | M | EX-02 |
| TCK-0504 | Assignment API: groups and individual students | Assigning a group creates one row per student; duplicates ignored | BE | S | 0502, 0302 | M | EX-04 |
| TCK-0505 | Publish check: blocks and warnings per PRD § 6.4 | Each block has a test; message names the item to fix | BE | M | 0503, 0504 | M | EX-05 |
| TCK-0506 | Publish: pin question versions, lock them, write `exam_version` snapshot + hash; only window end and assignments editable afterwards | Editing a published exam's settings returns an error naming the field | BE | M | 0505 | M | EX-06 |
| TCK-0507 | UI: exam list, overview, questions, settings (incl. proctoring section), students, publish | Teacher builds and publishes an exam through the UI | FE | L | 0408, 0502–0506 | M | EX-01..08 |

## E06 · Attempt engine and exam screen

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-0601 | `exam_attempt`, `attempt_question`, `answer`, `code_draft` tables; partial unique index (one non-voided attempt) | Two concurrent starts → one attempt (test) | DB | S | 0501 | M | ATT-02 |
| TCK-0602 | `domain_core`: timer maths (deadline, remaining, grace) with unit tests | Tests cover window cut-off, extension, grace | BE | S | 0001 | M | ATT-03 |
| TCK-0603 | Student exam list + exam detail APIs (available / upcoming / completed) | Only assigned, published exams appear | BE | S | 0504 | M | ATT-01 |
| TCK-0604 | Start attempt: all checks, deadline, shuffled order, full student payload, `server_time`, idempotency | Re-calling start returns the same attempt; payload has no keys (leak test) | BE | M | 0601, 0602, 0407 | M | ATT-01..05 |
| TCK-0605 | Batch autosave endpoint with `client_revision` upsert; flags; drafts; deadline + grace check | Out-of-order and repeated writes are harmless; late writes rejected | BE | M | 0604 | M | ATT-07, ATT-08, ATT-11 |
| TCK-0606 | Heartbeat: Redis-buffered, returns remaining time, teacher actions, fresh attempt token | Postgres written at most once a minute per attempt | BE | M | 0604 | M | ATT-04, ATT-12 |
| TCK-0607 | Submit (guarded update, receipt); sweeper every 30 s; lazy finalisation | Double submit returns the same receipt; overdue attempt auto-submitted within 30 s | BE | M | 0605 | M | ATT-10, ATT-11 |
| TCK-0608 | Teacher actions: extend, force-submit, void (reason, audit); voided attempt allows a restart | Extension visible on the student's next heartbeat | BE | S | 0607 | M | MON-02, ATT-02 |
| TCK-0609 | Teacher preview attempt (`is_preview`, excluded from results) | Preview works on a draft or published exam; not in results | BE | S | 0604 | M | EX-07 |
| TCK-0610 | FE: IndexedDB outbox + priority uploader + retry/backoff + time sync | Unit tests: queue survives reload; priority order respected | FE | L | 0007 | M | ATT-08, ATT-12 |
| TCK-0611 | FE: exam screen layout, header indicators, navigator, answer controls, sequential mode | Matches frontend § 6.1–6.5; keyboard operable | FE | L | 0610, 0604 | M | ATT-04..07 |
| TCK-0612 | FE: review & submit page, receipt, time-up modal, resume banner, session-expired modal, rules § 6.8 | Kill the browser mid-exam, reopen: all answers back | FE | M | 0611, 0607 | M | ATT-09..11 |
| TCK-0613 | FE: student dashboard and instructions pages | Three sections with correct states | FE | M | 0603 | M | ATT-01 |
| TCK-0614 | Network test: cut network for 2 min mid-exam, restore | 0 lost answers; status indicator correct throughout | QA | S | 0612 | M | G-02, ATT-12 |

## E07 · Coding questions (authoring)

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-0701 | `coding_config`, `test_case`, `reference_solution` tables | Migration applied | DB | S | 0401 | M | CQ-01..07 |
| TCK-0702 | Coding APIs: problem fields, languages + starter code, limits, comparison mode, test cases (CRUD, reorder, from examples) | Limits validated; ≥ 1 hidden case required before validation | BE | M | 0701, 0402 | M | CQ-01..07 |
| TCK-0703 | Hidden-case access only through one function; student view type for coding questions | Leak test: hidden markers never appear in any student response | BE | S | 0702 | M | CQ-05, NFR-02 |
| TCK-0704 | Test bundle builder job (tar + manifest + hash → storage `bundles`) | Bundle rebuilt on change; hash stored | BE | S | 0702, 0006 | M | — |
| TCK-0705 | Validation: reference solution → `exec.validation` job → report (per case time, > 50% warning); "needs validation" on edits | Bad reference fails validation; editing a case resets status | BE | M | 0704, 0806 | M | CQ-08, CQ-09 |
| TCK-0706 | UI: coding editor tabs (Problem, Languages & limits, Test cases, Validate) | Teacher creates and validates a coding question | FE | L | 0408, 0702, 0705 | M | CQ-01..09 |

## E08 · Code execution

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-0801 | Runner images: `cpp17`, `java21`, `python312`, `node22`; pinned digests; compile/run commands in `language` | Hello-world compiles and runs in each | INF | M | 0002 | M | CQ-02 |
| TCK-0802 | `sandbox-docker` (DinD) + `exec-worker`: per-case container with the full profile (security § 7.2); optional `runsc` | Profile flags verified by an inspection test | INF | L | 0801 | M | NFR-03 |
| TCK-0803 | Worker job flow: fetch bundle by URL, verify hash, compile once, run each case, capture output/time/memory, publish raw results, clean up | A job returns raw results on `exec.results`; no files left behind | BE | L | 0802, 0704 | M | — |
| TCK-0804 | `domain_core`: output comparison (EXACT, TRIM, TOKEN, NUMERIC) with test vectors | Vectors incl. CRLF, trailing newline, empty output, floats | BE | M | 0001 | M | CQ-06 |
| TCK-0805 | `domain_core`: coding score + verdict (PRD § 6.2), incl. worked example | Example gives 6.25 / PARTIAL; all rules tested | BE | S | 0001 | M | GRD-02 |
| TCK-0806 | `app-worker` result consumer: check job, compare, score, save `coding_evaluation` + `test_case_result`, counted submission, grading status | Duplicate result message is harmless; scores stored with weights | BE | M | 0803–0805 | M | EXE-05, GRD-02 |
| TCK-0807 | `code_run`, `coding_submission`, `coding_evaluation`, `test_case_result` tables | Migration applied | DB | S | 0601, 0701 | M | — |
| TCK-0808 | Run Code API (public cases only, rate limits, one in flight) + status endpoint | Never returns hidden data; limits enforced | BE | M | 0806, 0807 | M | EXE-02 |
| TCK-0809 | Submit Code API (counter under lock, 5 s gap, max) + status + history; student/teacher views | Concurrent submits can't exceed the max (test) | BE | M | 0808 | M | EXE-04, EXE-05 |
| TCK-0810 | Auto-submit last draft at attempt end | Draft newer than last submission gets graded; not counted toward limit | BE | S | 0809, 0607 | M | EXE-06 |
| TCK-0811 | Stuck-job retry (every 5 min); 3 failures → `FAILED` / `INTERNAL_ERROR`, no score | Killing the worker mid-job: job re-runs, no lost submission | BE | S | 0806 | M | EXE-07, EXE-08 |
| TCK-0812 | Sandbox attack tests: infinite loop, sleep, fork bomb, memory, output flood, disk fill, network, reading other files | Each gives the expected outcome, nothing escapes | QA | M | 0803 | M | NFR-03 |
| TCK-0813 | Run with custom input | Output shown, no comparison | Full | S | 0808 | S | EXE-03 |
| TCK-0814 | Re-evaluation of a question's submissions (new evaluation rows; result revision + notify) | Re-running changes scores and records revisions | BE | M | 0806, 0907 | S | EXE-09 |

## E09 · Grading and results

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-0901 | `domain_core`: objective scoring (MCQ, MSQ both modes, TF, negative marks, rounding, clamp) | Table of cases passes | BE | S | 0001 | M | GRD-01 |
| TCK-0902 | Objective grading job on submit | Re-running gives identical scores | BE | S | 0901, 0607 | M | GRD-01 |
| TCK-0903 | Grading status updates (pending → awaiting coding/manual → complete) | Status correct for every mix of question types | BE | S | 0902, 0806 | M | GRD-04 |
| TCK-0904 | Manual grading API: queue by question, anonymous by default, mark + feedback | Mark outside 0–points rejected; audit row | BE | M | 0903 | M | GRD-03 |
| TCK-0905 | Result computation + release (manual / on submit; blocked until complete) | Release refused while grading incomplete | BE | M | 0903 | M | GRD-05, GRD-06 |
| TCK-0906 | Student results APIs (released only) + history | Unreleased results return nothing | BE | S | 0905 | M | GRD-07, GRD-09 |
| TCK-0907 | Result revisions when a released score changes | Old/new score, reason, who recorded | BE | S | 0905 | M | GRD-08 |
| TCK-0908 | UI: grading page | Teacher marks 20 answers with keyboard only | FE | M | 0904 | M | GRD-03 |
| TCK-0909 | UI: results table, attempt detail (incl. coding score breakdown), release | Release button explains why it's disabled | FE | M | 0905 | M | GRD-05, GRD-06 |
| TCK-0910 | UI: student results list and detail | No keys, hidden data or events shown | FE | S | 0906 | M | GRD-07, GRD-09 |

**✅ M2 complete** (objective path: E04, E05, E06, E09)

## E06c · Coding in the exam screen

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-0615 | FE: coding panel — CodeMirror, language switch with per-language drafts, Run vs Submit, results (public full / hidden pass-fail), history | Matches frontend § 7; Run and Submit visually distinct | FE | L | 0611, 0808, 0809 | M | EXE-01..05 |

**✅ M3 complete** (coding path: E07, E08, TCK-0615)

## E10 · Proctoring — browser side

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-1001 | Consent: `consent_record` table, API, consent step UI; start blocked without consent | Camera never turns on before consent (test) | Full | M | 0604 | M | PRC-03 |
| TCK-1002 | Pre-check stepper: camera, mic, model download + Service Worker cache, connection test, screen size | All steps per frontend § 8.1; blocked permission shows help | FE | L | 1001 | M | PRC-04 |
| TCK-1003 | MediaPipe on the page (not a Web Worker: its loader fails in module workers; rate-governed instead): face count, face size, head pose at 3 fps (1 fps fallback) | ≤ 30% of one core on a mid-range laptop | AI | L | 1002 | M | PRC-05, NFR-07 |
| TCK-1004 | Detectors + rules engine: FACE_ABSENT, MULTIPLE_FACES, GAZE_AWAY, TAB_SWITCH; thresholds, presets, settling, merge, cooldown, 3-frame capture | Unit tests on recorded detector timelines | AI | L | 1003 | M | PRC-06 |
| TCK-1005 | Voice activity detection (Video + Audio only), no audio leaves the browser | Network log shows no audio upload | AI | M | 1003 | M | PRC-08 |
| TCK-1006 | Event and spot-check upload through the outbox (attempt token, budget 30, after-exam upload window); proctoring counter in heartbeat | Uploads wait behind answers; continue after submit | FE | M | 0610, 1004 | M | PRC-05 |
| TCK-1007 | Exam-screen proctoring UI: indicator, self-view, fullscreen prompt, camera-lost reconnect | No detection pop-ups shown to student | FE | S | 1004 | M | PRC-09, PRC-14 |

## E11 · Proctoring — server side and review

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-1101 | `proctoring_event` table with constraints (decision needs reviewer; no severity before check) | Constraints tested | DB | S | 0601 | M | PRC-07, PRC-10 |
| TCK-1102 | Upload endpoints: attempt-token auth, type/size checks, re-encode (strip EXIF), storage `tmp/`, event `PROCESSING`, enqueue check; response reveals nothing (built: `POST /attempts/{id}/captures`; event pictures go straight to `evidence`, only spot checks use `tmp/`) | Fake JPEG rejected; EXIF gone; rate limits work | BE | M | 1101 | M | PRC-05, PRC-07 |
| TCK-1103 | `inference-worker`: RT-DETR r18 (phone, book, people) and YuNet (faces), baked into the image; returns findings only, app-worker decides; GPU optional (liveness moved to its own step; no stub: tests feed findings directly) | Works on CPU; returns verdict on sample images | AI | L | 0002 | M | PRC-06, PRC-07 |
| TCK-1104 | Verdict consumer in `app-worker`: move images to `evidence/` or delete; set status/severity; confidence < 0.6 lowers severity | Rejected events never appear in any API | BE | M | 1102, 1103 | M | PRC-07 |
| TCK-1105 | Rule-based severity for no-image events (TAB_SWITCH, VOICE_DETECTED); SIGNAL_LOST from heartbeat counter (only when heartbeats arrive) | Network loss never creates SIGNAL_LOST (test) | BE | M | 1101, 0606 | M | PRC-06, PRC-14 |
| TCK-1106 | Review APIs: events per attempt, evidence signed URL (5 min, audited), review decision, integrity outcome | Student routes never return events (test) | BE | M | 1104 | M | PRC-09..11 |
| TCK-1107 | Evidence retention job (hourly) + overdue count on admin settings | Expired evidence deleted; count = 0 | BE | S | 1104 | M | PRC-13, G-08 |
| TCK-1108 | UI: review list, attempt timeline with connection gaps, evidence viewer, decisions | Teacher reviews a full attempt by keyboard | FE | L | 1106 | M | PRC-10, PRC-11 |
| TCK-1109 | Bulk dismiss LOW/MEDIUM | HIGH can't be bulk-dismissed | Full | S | 1106 | S | PRC-12 |
| TCK-1110 | Detector quality view (dismissal rates) | Rates per detector per exam | Full | S | 1106 | S | PRC-15 |

**✅ M4 complete**

## E12 · Monitoring and analytics

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-1201 | Monitor API (from Redis heartbeat data): status, progress, time left, connection, unsynced answers, event counts | 200-student exam responds < 500 ms | BE | M | 0606 | S | MON-01 |
| TCK-1202 | Monitor UI with extend / force-submit / void actions | Actions work with reason dialog | FE | M | 1201, 0608 | S | MON-01, MON-02 |
| TCK-1203 | Analytics API: exam stats, per-question stats, coding verdicts and per-test-case pass rates | Numbers match a hand-computed sample | BE | M | 0905, 0806 | S | MON-03..05 |
| TCK-1204 | Analytics UI | Low pass-rate test cases highlighted | FE | M | 1203 | S | MON-03..05 |

## E13 · Notifications

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-1301 | `notification` table, APIs, events: exam assigned, result released, result changed | Created on each event | BE | S | 0905 | S | NOT-02 |
| TCK-1302 | Notification bell + page | Unread count updates | FE | S | 1301 | S | NOT-02 |
| TCK-1303 | Result-released email | Email arrives in Mailpit | BE | S | 1301, 0201 | S | NOT-03 |

## E14 · Quality and demo

| ID | Ticket | Done when | Area | Size | Needs | P | PRD |
|---|---|---|---|---|---|---|---|
| TCK-1401 | Security suite: role matrix, wrong-owner/wrong-institution, hidden-test leak, proctoring privacy, late writes, idempotency (security § 11) | All in CI and passing | QA | L | M4 | M | NFR-01..03 |
| TCK-1402 | End-to-end tests (Playwright): objective exam, coding exam, proctored exam, network cut | Four paths pass in CI | QA | L | M4 | M | NFR-14 |
| TCK-1403 | Load test (k6 or Locust): 200 students autosaving + 100 simultaneous submissions | Meets NFR-04, NFR-05, G-03, G-04 | QA | M | M3 | M | NFR-04, NFR-05 |
| TCK-1404 | Proctoring calibration: honest and staged-cheating runs, tune thresholds, record results | G-06 and G-07 measured; table for the report | AI | M | M4 | M | G-06, G-07 |
| TCK-1405 | Accessibility pass: `axe` in CI + keyboard-only exam run | No serious `axe` issues on main pages | QA | S | M4 | M | NFR-11 |
| TCK-1406 | Backups: nightly `pg_dump` + storage copy, 7-day keep; restore tested once | Restore into a fresh stack works | INF | S | 0002 | M | NFR-13 |
| TCK-1407 | Demo deployment: HTTPS at nginx, real SMTP, seed demo data (institution, users, sample exams) | Fresh machine to running demo following the README | INF | M | M4 | M | — |
| TCK-1408 | Consent text and README / user guide | Consent covers all points in security § 8.2 | Docs | S | 1001 | M | PRC-03 |

---

## Coverage check

Every Must requirement in the PRD maps to at least one ticket:

| PRD area | Tickets |
|---|---|
| AUTH-01..07 | 0102–0106, 0110 |
| ACC-01..05 | 0004, 0107, 0108, 0404 |
| USR-01..04 | 0101, 0301, 0302, 0305, (0306 S) |
| QB-01..09 | 0401–0408 |
| CQ-01..09 | 0701–0706, 0801, 0804 |
| EX-01..08 | 0501–0507, 0609 |
| ATT-01..12 | 0601–0614 |
| EXE-01..09 | 0615, 0806, 0808–0811, (0813, 0814 S) |
| GRD-01..09 | 0805, 0806, 0901–0910 |
| PRC-01..15 | 0507 (settings), 1001–1007, 1101–1108, (1109, 1110 S) |
| MON-01..05 | 0608 (actions), (1201–1204 S) |
| NOT-01..03 | 0201, (1301–1303 S) |
| AUD-01..03 | 0109, 0304, 0305 |
| NFR-01..14 | 0002, 0008, 0614, 0703, 0802, 0812, 1003, 1401–1406 |
