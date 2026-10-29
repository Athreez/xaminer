# Security and Access — CBT Platform with AI Proctoring and Automated Coding Evaluation

| Field | Value |
|---|---|
| Document | 3 of 5 — Security and Access |
| Status | Draft v0.2 — under review |
| Last updated | 2026-10-24 |
| Code | None yet. This document comes first. |

**This document owns:** permission names and the role table, trust zones, the sandbox profile, privacy
rules for proctoring, and the threat list. Requirement IDs (`AUTH-01` …) come from `PRD.md`; services,
tables and endpoints from `TECHNICAL_ARCHITECTURE.md`.

---

## 1. Trust zones

| Zone | What is in it | Trusted? | Database access |
|---|---|---|---|
| **Z1 — Trusted** | `api`, `app-worker`, `scheduler` | Yes, but checks everything it receives | Yes |
| **Z2 — Untrusted input handlers** | `exec-worker` (handles student code), `inference-worker` (handles student images) | No — their output is checked by Z1 | **No** |
| **Z3 — Hostile** | Sandbox containers, student code, the browser and anything it sends | Never | No |

Two decisions define the security of the whole system:

1. **Code runs far from the data.** Student code runs in a container with no network, started by a worker
   that has no database credentials, on a separate Docker engine, on a Docker network that cannot reach
   Postgres. The worker returns raw output; Z1 compares it and computes the score.
2. **The browser is never believed.** Not its clock, not a score, not a severity, not a role. The server
   decides all of these from its own data.

---

## 2. Authentication

### 2.1 Accounts and passwords

| Topic | Rule |
|---|---|
| Account creation | Only by an admin (or the `platform-admin` CLI for the first admin). No self-sign-up |
| Invitation | Random 256-bit token, stored hashed, single use, expires in 7 days. Re-sending cancels the old one. A weak password at activation is refused but leaves the link usable |
| Password | 10–128 characters (the cap stops very long inputs being used to slow the server); not on the common-password list (`backend/app/auth/common_passwords.txt`); not mostly one repeated character; must not contain the user's email name or a name part of 4+ letters. Hashed with Argon2id; re-hashed at login if the parameters get stronger |
| First admin | Created with `platform-admin create-admin`; the password is typed at a hidden prompt (or piped with `--password-stdin`), never passed as an argument, so it never lands in shell history |
| Password reset | Same token rules, expires in 1 h. Response is identical whether the email exists or not (and over the rate limit). A reset logs out all sessions and clears any lockout. A person with accounts in several institutions gets one link per account |
| Links in emails | Tokens go after `#` (`/activate#token=…`, `/reset-password#token=…`). Browsers never send that part to the server, and the API takes tokens in the request body, never the URL, so tokens can't reach nginx or API logs (checked). Every bad link (unknown, used, expired, wrong kind) gets the same `INVALID_TOKEN` |
| Lockout | 5 wrong passwords in a row → locked 15 min; a success resets the count, and the count restarts when it locks. Counted in one atomic UPDATE. Guesses while locked don't extend the lock. If the same email has accounts in several institutions, only a total miss counts. "Account locked" is only shown when the password was correct, so it can't be used to discover accounts. Trade-off: anyone who knows an email can lock it for 15 min; the per-IP limit slows this, and an admin unlock comes with the admin user tools |
| Login errors | Wrong email and wrong password return the same error (`INVALID_CREDENTIALS`) with similar timing |

### 2.2 Tokens

| Token | Form | Lifetime | Stored where | Notes |
|---|---|---|---|---|
| Access token | JWT (HS256, algorithm pinned on decode): user id, role, institution id, type | 15 min | Browser memory only (not localStorage) | Sent as `Authorization: Bearer`. Signed with `JWT_SECRET`; the API refuses to start if it is missing, under 32 characters or still the example placeholder |
| Refresh token | Random 256-bit string, stored as SHA-256 | 7 days | `xaminer_refresh` cookie: `HttpOnly`, `Secure`, `SameSite=Strict`, path `/api/v1/auth` | Rotated on every use (`POST /auth/refresh`; the row is locked while checked). Using an already-used token revokes the whole session family (it means the token was copied): `TOKEN_REUSE_DETECTED`. Exception: within 10 s of rotation the answer is `TOKEN_ALREADY_ROTATED` with no revocation, because two tabs refreshing at once look the same; the slower tab already has the new cookie and retries. Each refresh extends the session by 7 days |
| Attempt token | JWT with scope `proctoring-upload`, one attempt id | 10 min, renewed by heartbeat; usable for uploads up to 30 min after the attempt ends | Browser memory | Only accepted by the two proctoring upload endpoints, and only for that attempt |

Changing a user's role, email or password, or deactivating them, revokes all their refresh tokens.
A deactivated user's still-valid access token stops working at once on `/auth/me`, which checks the
account is active.

Admins can't deactivate themselves or change their own role, and the last active admin of an
institution can't be deactivated or demoted (the admin rows are locked while checked, so two admins
can't remove each other at once). Admins can unlock a locked account and send reset or invitation
emails, but never see or set a password.

**Login does the same work whatever the outcome.** An unknown email still runs a full password check
against a dummy hash, so response time doesn't reveal which emails have accounts. Unknown email, wrong
password, invited (no password yet) and deactivated accounts all get the identical
`INVALID_CREDENTIALS` answer.

---

## 3. Permissions

### 3.1 Model

- Three fixed roles: `ADMIN`, `TEACHER`, `STUDENT`. One role per user. No custom roles.
- Permissions are named `resource:action` and mapped to roles **in code** (`backend/app/authz/permissions.py`),
  not in a database table.
- Every route declares the permission it needs (`require(P.…)`) or that it is deliberately open (`PUBLIC`).
  **A route with no declaration makes the app refuse to start**, so a forgotten check is caught before it
  ships. The check also refuses to start if it finds no routes at all, so it can't pass by checking
  nothing (FastAPI 0.162 stores included routers nested; the check walks them with
  `iter_route_contexts`). A missing permission answers `403 FORBIDDEN`; no or bad login, `401`.
- A permission alone is never enough: after loading the item, an **ownership check** confirms this user may
  act on this particular item (§ 4).
- Role and institution always come from the verified token, never from the request.

### 3.2 Role table

**own** = the user's own items · **own exams** = exams the teacher owns · **inst** = the whole institution ·
**—** = no access.

**Users and setup**

| Permission | Admin | Teacher | Student |
|---|---|---|---|
| `user:read` | inst | self + students assigned to own exams (name, roll no.); when assigning an own exam, a search of the institution's students (name, email, roll no.) | self |
| `user:write` (create, edit, deactivate, invite, import) | inst (cannot deactivate self) | — | — |
| `user:change-password` | self | self | self |
| `group:read` | inst | inst (to assign exams) | — |
| `group:write` | inst | — | — |
| `institution-settings:write` | inst | — | — |
| `audit-log:read` | inst | — | — |

**Questions**

| Permission | Admin | Teacher | Student |
|---|---|---|---|
| `question:read` (incl. answer keys, rubric) | — | own + institution-shared | — |
| `question:write` (create, edit, archive) | — | own | — |
| `question:copy` | — | own + institution-shared | — |
| `test-case:read-hidden` | — | own | **—** |
| `test-case:write`, `reference-solution:write`, `question:validate` | — | own | — |

**Exams and attempts**

| Permission | Admin | Teacher | Student |
|---|---|---|---|
| `exam:read` | inst (title, dates, status only) | own exams | assigned exams (student view only) |
| `exam:write` (edit, assign, publish, archive, delete) | — | own exams | — |
| `attempt:take` (start, save, run, submit) | — | own preview attempt | own, only if assigned |
| `attempt:read` (answers, code) | — | own exams | own |
| `attempt:manage` (extend, force-submit, void — reason required) | — | own exams | — |
| `submission:read-full` (source, hidden case details) | — | own exams | **—** |
| `submission:read-student-view` | — | — | own |
| `submission:re-evaluate` | — | own exams | — |

**Grading and results**

| Permission | Admin | Teacher | Student |
|---|---|---|---|
| `grading:write` (marks, feedback) | — | own exams | — |
| `result:read` | — | own exams | own, **released only** |
| `result:release` | — | own exams | — |
| `analytics:read`, `monitor:read` | — | own exams | — |

**Proctoring**

| Permission | Admin | Teacher | Student |
|---|---|---|---|
| `proctoring:upload` | — | own preview attempt | own attempt, **attempt token only** |
| `proctoring-event:read` | — | own exams | **—** |
| `evidence:read` (5-min signed URL, audit-logged) | — | own exams | **—** |
| `proctoring-event:review` | — | own exams | — |
| `consent:read` | — | own exams (accepted or not, when) | own |
| `integrity-outcome:read` | — | own exams | own, released result only |

**Own account and notifications** (`account:self`, `notification:read`): every role; each user reaches
only their own (`/auth/me`, log out everywhere, own notifications).

**Why the admin is kept out of academic content.** The admin manages accounts, not exams. An admin who can
read answer keys, hidden tests, student answers or evidence is one account whose theft ruins every exam
in the college. So admins see that exams and attempts exist, never their content.

**Why students see so little about proctoring.** Showing events, severities or confidence would let a
student learn exactly what the detectors catch. Students only see the final integrity outcome on a
released result.

---

## 4. Data protection rules

### 4.1 Ownership and isolation

| Rule | How |
|---|---|
| Tenant isolation | Every table has `institution_id`; repository helpers add the filter automatically from the token |
| No guessing | IDs are UUIDs, not counting numbers |
| Hide existence | Another institution's item, another teacher's exam or another student's attempt returns `404`, not `403` |
| Load, then check | Ownership is checked on the loaded item, never on the ID alone: `get_owned()` (`backend/app/authz/ownership.py`). It also re-compares the institution, because SQLAlchemy can return an item from session memory without a query (bypassing the automatic filter) |
| Every ID route is tested | Each route with an ID in its path must be registered in `tests/db/test_owned_routes.py`; the test calls it as the owner (works), a same-institution neighbour (404) and an outsider (404). An unregistered ID route fails the build |
| No protected fields from the client | Request schemas reject unknown fields. No endpoint accepts `score`, `role`, `institution_id`, `deadline_at`, `severity` or `owner_id` |
| Student views | Student responses are built from separate "student view" types field by field. Fields are never removed from a full object, because a forgotten removal is a leak |

### 4.2 Hidden test cases

Several separate protections, so one mistake isn't enough to leak them:

1. Hidden cases are read only by one function in `questions`, which is never used to build student views.
2. Student result views carry only order number, label and pass/fail for hidden cases — no input, output
   or timing (timings reveal input size).
3. Run Code only ever receives public cases.
4. The worker gets them inside a bundle through a 5-minute link to one file; nothing else in the job.
5. Logs never contain test case data.
6. **Leak test in CI:** hidden cases are filled with unique marker strings, every student endpoint is
   called, and the test fails if any marker appears.

### 4.3 Answer keys and rubrics

Correct options and rubrics are only in teacher views. Student result views show the student's own answer
and score, not the correct answer.

---

## 5. Web and API security

### 5.1 Browser protections

| Control | Setting |
|---|---|
| HTTPS | Required in deployment (nginx); HSTS on |
| CSRF | API calls use the `Authorization` header, so they are not exposed to CSRF. The refresh cookie is `SameSite=Strict`, POST-only, and the server checks the `Origin` header |
| Open redirect | After login the app only follows `?next=` if it is a path on this site; full URLs, `//host`, backslash and control-character tricks are ignored (unit-tested) |
| CORS | Not needed: the app and API share one origin through nginx. Cross-origin requests are refused |
| Content Security Policy | `default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; img-src 'self' blob: data: <storage-origin>; connect-src 'self'; worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'` |
| Other headers | `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=(self), microphone=(self), geolocation=()` |

`'wasm-unsafe-eval'` is needed by the in-browser MediaPipe models. MediaPipe files are served from our
own server, not a CDN.

### 5.2 Input and output

| Concern | Rule |
|---|---|
| Validation | Every request body is validated by a Pydantic schema on the server; unknown fields are rejected |
| SQL injection | SQLAlchemy with bound parameters only; no SQL built with string formatting |
| XSS | Question text is Markdown. On save the server removes HTML tags and unsafe link schemes from prose (code is kept as typed). The one shared renderer (`MarkdownView`) never renders raw HTML, keeps an allow-list of elements (`rehype-sanitize`) and allows only http(s), mailto and relative links. React escapes everything else |
| Size limits | Request body caps per route (e.g. answer text 64 KB, code 256 KB, test case 1 MB, image 2 MB) |
| Errors | Error responses never include stack traces or SQL |

### 5.3 Rate limits

Stored in Redis so they apply across all API processes.

| Action | Limit |
|---|---|
| Login | 10 per minute per IP; 5 failures lock the account |
| Password reset request | 3 per hour per email |
| Autosave | 2 requests per second per attempt |
| Run Code | 1 per 8 s, 20 per question per attempt |
| Submit Code | 5 s between submissions; question's max (default 10) |
| Proctoring event upload | 6 per minute per attempt; max 30 events with images per attempt |
| Spot check | 1 per 15 s per attempt |

`429` responses always include `Retry-After` (seconds).

The per-IP limit only works if the IP can't be faked: nginx **overwrites** `X-Forwarded-For` with the
real connecting address instead of appending to it, so a client-sent header is ignored (tested: 12
requests with 12 fake addresses are still limited as one).

### 5.4 File uploads

| Upload | Checks |
|---|---|
| Question images | Type checked by file content (not extension): PNG/JPEG/WebP only, ≤ 2 MB, at most 40 million pixels. Re-encoded to WebP (EXIF and anything hidden removed, longest side ≤ 2000 px). Stored as `<institution>/<id>.webp`; question text keeps `/api/v1/images/<id>`, swapped for a signed link when sent. nginx serves `/images/` read-only from storage, so storage is never exposed |
| Proctoring frames | JPEG only, ≤ 640×480, ≤ 512 KB each, ≤ 3 per event. Re-encoded on the server, which removes EXIF data (can contain GPS location). Stored with random names that contain no student information |
| CSV import | ≤ 1 MB, ≤ 2,000 rows, sent as text in JSON (no file upload) and parsed strictly as text; cells beginning with `=`, `+`, `-`, `@` are escaped in any export |

### 5.5 Secrets

- All secrets (DB passwords, JWT key, storage keys, SMTP password) live in `.env`, which is git-ignored.
  `.env.example` lists the names with dummy values.
- `exec-worker` and `inference-worker` receive **no** database or storage credentials — only Redis access and
  short-lived pre-signed URLs inside each job.
- Logs never contain passwords, tokens, answers, source code, test case data or evidence file names.
  The API logs paths without query strings; Celery's task arguments and return values are stripped from
  worker logs (tested).
- Celery accepts JSON messages only, never pickle, because the untrusted workers can write to Redis.

### 5.6 Database permissions

| DB user | Can |
|---|---|
| superuser (`POSTGRES_USER`) | Everything. Only the `postgres` and one-off `db-init` containers have its password |
| `migrator` | Owns the schema; used only by the one-off `migrate` service (Alembic) |
| `app` | Read/write rows on all tables except `audit_log`, where it can only `INSERT` and `SELECT`. Cannot create, alter, drop or truncate tables (tested) |

So the audit log is append-only by database rule, not just by convention, and a bug or injection in the
API cannot change the schema. `api` and `app-worker` only ever receive the `app` password.

---

## 6. Exam integrity

| Threat | Protection |
|---|---|
| Changing the computer clock to gain time | The deadline is stored on the server; every write after `deadline + 60 s` is rejected; the sweeper auto-submits |
| Sending answers after time is up | Same — every write checks the deadline and that the attempt is still in progress |
| Faking a score | No endpoint accepts a score from a student. All scoring happens on the server in `domain_core` |
| Starting two attempts at once | Database unique index: one non-voided attempt per student per exam |
| Seeing questions before the exam | Exam content is only delivered when an attempt starts inside the window |
| Getting the answer key | Never in any student response (§ 4.3) |
| Counting a grade twice | Grading jobs are idempotent; re-evaluation adds a new evaluation row; only one submission is "counted" per question |
| Teacher publishes a broken hidden test | Validation with a reference solution is required before publishing; per-test-case pass rates show anomalies; re-evaluation fixes it |
| Students sharing questions during the exam | **Only partly handled**: shuffling and proctoring help, but can't prevent it. Stated as a limitation |

---

## 7. Code execution security

### 7.1 Assumption

Assume every submission is written by someone actively trying to break out, read other submissions,
reach the network, crash the machine, or forge a grade.

### 7.2 Layers

| Layer | Protection |
|---|---|
| Container | Fresh container **per test case**: no network, read-only filesystem, small temporary work folder, non-root user, all Linux capabilities dropped, no privilege escalation, default seccomp filter |
| Limits | Memory (no swap), 1 CPU, 64 processes, 64 KB output, wall-clock kill at 2× time limit |
| Engine | Containers run on `sandbox-docker`, a separate Docker engine, not the host's |
| Network | `exec-worker` and `sandbox-docker` sit on a Docker network that has no route to Postgres |
| Credentials | `exec-worker` holds no DB or storage credentials; one 5-minute link per job, for one bundle file |
| Scoring | The worker never compares output or computes scores; `app-worker` does, after checking the job exists and is running |
| Images | Language images pinned by digest; rebuilt and scanned regularly |
| Optional | gVisor (`--runtime runsc`) for a second kernel boundary |

**Honest note on Docker-in-Docker.** `sandbox-docker` must run privileged. If student code escaped its
container, it would land inside that privileged engine, from which reaching the host is easier. So DinD
gives *separation* (student containers can't see or touch platform containers, and the worker doesn't hold
the host's Docker socket), not a strong wall. The strong protections are the container settings above.
For real deployment, use gVisor or run `sandbox-docker` on a separate VM.

### 7.3 Attacks and responses

| Attack | Result |
|---|---|
| Infinite loop | Killed at the time limit → `TIMEOUT` |
| `sleep` forever (uses no CPU) | Wall-clock kill → `TIMEOUT` |
| Fork bomb | Process limit stops it → `RUNTIME_ERROR` |
| Allocating huge memory | Memory limit → `MEMORY_LIMIT` |
| Printing gigabytes | Output read stops at 64 KB → `OUTPUT_LIMIT` |
| Filling the disk | Work folder is a small size-capped tmpfs; root filesystem is read-only |
| Network access (download answers, attack servers) | No network interface exists in the container |
| Reading other students' code or test cases | Each container sees only its own source and one input; containers are destroyed after each case |
| Remembering earlier test cases | Fresh container per case; nothing carries over |
| Huge compile (template bombs) | Compile step has its own time and memory limits → `COMPILE_ERROR` |
| Forging a "passed" result | The worker doesn't decide pass/fail; Z1 compares outputs against expected output from the database |

**Remaining risk:** a fully compromised `exec-worker` could report false output for the jobs it handles.
It could not read the database, other students' data, or score anything itself.

### 7.4 Local development

On a developer laptop the sandbox may run without gVisor. That is fine for development but must not be
described as equivalent to the deployed setup.

---

## 8. Proctoring privacy

### 8.1 Principles

| Principle | Where it is enforced |
|---|---|
| No recordings | No endpoint accepts video or audio streams; only ≤ 3 still images per event |
| No audio stored | Voice detection runs in the browser; audio is never uploaded |
| Least data | Images ≤ 640×480; spot-check frames deleted within minutes unless they show something |
| Consent first | Camera/microphone are not turned on before the student accepts consent; starting an attempt without a consent record is refused |
| Humans decide | Only a teacher's review sets `FLAGGED`; a DB constraint requires a named reviewer for every decision |
| Never changes the score | `proctoring` module cannot call `grading` or `results`; score and integrity outcome are separate columns |
| Stays on our server | No student image is sent to any third-party service; models run on `inference-worker` |
| Deleted on time | Scheduled job deletes evidence after the retention period |

### 8.2 Consent text must state

1. That the camera (and microphone, in Video + Audio mode) will be used during the exam.
2. That analysis happens on the student's own device, and no video or audio is recorded.
3. That a few still images are saved only when something possibly suspicious is detected.
4. Who can see them: the teacher who owns the exam. Not other students, not the admin.
5. How long they are kept (the institution's retention setting) and that they are then deleted.
6. That nothing is decided automatically: a teacher reviews every event.
7. What happens if the student declines (they can't take that exam; contact the teacher).

The accepted text's hash is stored with each consent record, so it is always known which wording a
student agreed to.

### 8.3 Evidence storage and access

| Topic | Rule |
|---|---|
| Storage | Storage bucket `evidence`, private, no public access. Keys are random (`ev/{institution}/{yyyy}/{mm}/{random}.jpg`) |
| Viewing | Teacher of the exam only, via a signed URL valid 5 minutes for one image. Every URL issued is audit-logged |
| Bulk download | Not available |
| Other buckets | `bundles` (test bundles) and `images` (question images) are also private; question images are delivered with signed URLs valid for the exam duration |

### 8.4 Retention

| Data | Kept for | Deleted by |
|---|---|---|
| Evidence images | Institution setting, default 30 days (7–90) after the exam closes | Hourly cleanup job |
| Spot-check frames with no finding | Minutes | Cleanup job |
| Rejected events and their images | Deleted immediately | `app-worker` |
| Proctoring event records (no images) | As long as the result | — |
| Consent records | As long as the result | — |
| Code Run records | 24 h | Daily cleanup job |
| Audit log | 3 years | Manual archive |

The cleanup job counts overdue items; anything overdue is shown as an error on the admin page.

### 8.5 Who sees what

| | Admin | Teacher (own exams) | Student |
|---|---|---|---|
| Event list, severity, confidence | — | ✓ | — |
| Evidence images | — | ✓ (logged) | — |
| Review notes | — | ✓ | — |
| Integrity outcome | — | ✓ | ✓ (on released result) |
| Own consent record | — | ✓ | ✓ |

### 8.6 Known limits (stated, not hidden)

- **A determined student can partly evade detection** (e.g. covering the camera at the right moment,
  using a second device out of view). Spot checks and `SIGNAL_LOST` make this harder, not impossible.
  Teachers are told this in the review screen.
- **Detectors may work less well for some people** (lighting, skin tone, glasses, head coverings,
  disabilities). Mitigations: human review of every event, per-detector dismissal rates, calibration with
  varied people and lighting, and no automatic decisions.

---

## 9. Threat list

| ID | Threat | Impact | Protection (section) |
|---|---|---|---|
| T-01 | Password guessing / credential stuffing | Medium | Lockout, IP rate limit, common-password check (§ 2.1, § 5.3) |
| T-02 | Stolen refresh token | High | HttpOnly cookie, rotation, family revocation on reuse (§ 2.2) |
| T-03 | Finding which emails have accounts | Low | Same responses for existing and unknown emails (§ 2.1) |
| T-04 | Changing own role | Critical | Role only from signed token; no endpoint accepts it (§ 3.1, § 4.1) |
| T-05 | Reading another student's attempt or result | High | Ownership check on loaded item, 404, UUIDs (§ 4.1) |
| T-06 | Reading another institution's data | Critical | Automatic tenant filter, 404 (§ 4.1) |
| T-07 | Route shipped with no permission check | Critical | App won't start (§ 3.1) |
| T-08 | Hidden test cases leaked | High | Six protections + CI leak test (§ 4.2) |
| T-09 | Gaining time / late answers | High | Server deadline, write checks, sweeper (§ 6) |
| T-10 | Faking a score | Critical | No score input anywhere; server-side scoring (§ 6) |
| T-11 | Sandbox escape | Critical | Container profile, DinD separation, optional gVisor (§ 7) |
| T-12 | Student code reaching network or database | Critical | No network in container; no DB route or credentials for the worker (§ 7.2) |
| T-13 | Student code exhausting the server | High | CPU, memory, process, output, disk limits; separate queues (§ 7.3) |
| T-14 | Worker forging grades | High | Scoring only in Z1 (§ 7.2) |
| T-15 | Evidence exposed through a public bucket or leaked URL | Critical | Private buckets, 5-min one-file URLs, random keys (§ 8.3) |
| T-16 | Evidence kept past its deadline | High | Hourly deletion job, overdue alert (§ 8.4) |
| T-17 | Evidence viewed without reason | High | Teacher-only, every view logged (§ 8.3) |
| T-18 | Student images sent to third parties | High | Self-hosted models only (§ 8.1) |
| T-19 | Student disabling detection | Medium | Spot checks, `SIGNAL_LOST`, server re-check; partly unsolvable (§ 8.6) |
| T-20 | False alarm leads to an unfair decision | Critical | Human review always, no auto-penalties, conservative thresholds (§ 8.1) |
| T-21 | Detectors unfair to some groups | Critical | Human review, dismissal rates, calibration (§ 8.6) |
| T-22 | Camera used before consent | High | Camera starts only after consent; attempt start requires consent record (§ 8.1) |
| T-23 | Stolen attempt token | Low | Upload-only, one attempt, short-lived (§ 2.2) |
| T-24 | Malicious image upload (fake type, huge decompression) | Medium | Content-type check, size/dimension caps, re-encoding (§ 5.4) |
| T-25 | SQL injection | Critical | Bound parameters only (§ 5.2) |
| T-26 | XSS through question text or feedback | High | Sanitised Markdown, single renderer, CSP (§ 5.1, § 5.2) |
| T-27 | Secrets in git or logs | Critical | `.env` git-ignored, log redaction (§ 5.5) |
| T-28 | Audit log edited to hide an action | High | DB user has no UPDATE/DELETE on `audit_log` (§ 5.6) |
| T-29 | Vulnerable dependency or runner image | High | Lockfiles, `pip-audit`/`npm audit` in CI, pinned images (§ 7.2) |
| T-30 | Server overloaded on exam day | High | Rate limits, queue never drops submissions, Run Code slowed first, attempts never terminated |

---

## 10. Audit log

| Property | Rule |
|---|---|
| Append-only | The `app` DB user can't update, delete or truncate rows (§ 5.6; revoked in migration 0004, tested) |
| Same transaction | `audit.record()` adds the row to the same transaction as the change, so a change can't happen without its record and a failed change leaves none (tested) |
| Content | Who (user and role; `PLATFORM` for `platform-admin` commands; none for a failed login), what (action), which item, when, IP, browser, request ID, and changed fields (`{"field": {"old", "new"}}`) |
| No sensitive content | Never stores answers, code, passwords, tokens or evidence — only IDs and changed-field summaries. Password and token fields are dropped by `record()` even if passed |
| Actions | The list in `PRD.md` AUD-02. Recorded so far: `auth.login`, `auth.login_failed`, `auth.account_locked`, `auth.logout`, `auth.logout_all`, `auth.token_reuse_detected`, `auth.invitation_accepted`, `auth.password_reset`, `institution.created`, `user.created`, `user.invited`, `user.invitation_resent`. Failed logins for unknown emails have no institution to file under, so they aren't recorded (the per-IP limit covers them) |
| Access | Admin only, searchable |

---

## 11. Security tests (run in CI)

| Test | Checks |
|---|---|
| Permission declared | Every route has a permission |
| Role matrix | Every route called as each role; result matches § 3.2 |
| Wrong owner | Every `/{id}` route called with another user's / institution's ID → `404` |
| Hidden test leak | Marker strings in hidden cases never appear in student responses (§ 4.2) |
| Proctoring privacy | No student-callable route returns events, severity, confidence or evidence |
| Late writes | Writes after deadline + grace are rejected |
| Idempotency | Repeating start, autosave, submit, run, submit-code gives the same result |
| Sandbox | Programs for each attack in § 7.3 produce the expected outcome and no side effects |
| Rate limits | Limits apply and `429` has `Retry-After` |
| Dependencies | `pip-audit` and `npm audit` fail the build on high-severity issues |
