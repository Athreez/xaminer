# Product Requirements — CBT Platform with AI Proctoring and Automated Coding Evaluation

| Field | Value |
|---|---|
| Document | 1 of 5 — Product Requirements |
| Status | Draft v0.2 — scope agreed, under review |
| Last updated | 2026-10-24 |
| Code | None yet. This document comes first. |

## The five documents

| Document | Owns |
|---|---|
| **PRD.md** (this file) | What the product does: features, rules, scope, requirement IDs |
| `TECHNICAL_ARCHITECTURE.md` | How it is built: services, stack, tables, enums, API, flows |
| `SECURITY_AND_ACCESS.md` | Who can do what (permissions), threats and protections |
| `FRONTEND_SPEC.md` | Pages, routes, screen states |
| `FEATURE_TICKETS.md` | Tickets and build order |

If two documents disagree, the owner of that topic wins; fix the other one.

## Terms

| Term | Meaning |
|---|---|
| **Institution** | A college using the platform. Owns its users, questions, exams and evidence |
| **Exam** | A test: settings, questions, schedule, proctoring setup |
| **Question** | A reusable item in the **Question Bank** |
| **Exam Question** | A question placed in an exam, with its points and position |
| **Test Case** | One input + expected output for a coding question; **public** (student can see it) or **hidden** |
| **Attempt** | One student's sitting of one exam |
| **Code Run** | Running code against public test cases for feedback. **Never graded** |
| **Coding Submission** | Official code submission, graded against all test cases including hidden ones |
| **Result** | An attempt's final score and breakdown |
| **Proctoring Event** | Something the system flagged as possibly suspicious. **Not** a finding of cheating |
| **Evidence** | Up to 3 still images attached to a proctoring event. Never video |
| **Review** | A teacher's decision on an event: `DISMISSED` or `FLAGGED` |
| **Integrity Outcome** | Per-attempt summary of the teacher's reviews |

Two distinctions matter everywhere:
1. **Code Run ≠ Coding Submission.** A Run is feedback; a Submission is graded.
2. **Proctoring Event ≠ cheating.** Only a teacher's review can confirm a concern, and it never changes the
   score automatically.

---

## 1. Overview

### 1.1 What it is

A web-based computer-based testing (CBT) platform for colleges. Teachers build exams from a question bank
(MCQ, MSQ, True/False, descriptive, coding), assign them to students, and review results. Students take
exams in the browser. Two features set it apart from a quiz tool:

- **Automated coding evaluation.** Students write code in the browser, run it against sample tests, and
  submit it for grading against hidden tests. Code runs in isolated sandboxes.
- **AI-assisted proctoring with a human decision.** The webcam (and optionally microphone) is analysed in
  the browser. Suspicious moments become events with a few still images. A teacher reviews each one. No
  video is recorded and the AI never decides anything.

### 1.2 Problem

| Who | Problem |
|---|---|
| College | Quizzes, coding tests and proctoring are spread over different tools with different privacy rules |
| Teacher | Checking programming answers by hand is slow; proctoring tools give unexplained "cheating scores" |
| Student | Exam sites lose answers on bad internet and give no feedback while coding |

### 1.3 Users

| Role | Who | Main jobs |
|---|---|---|
| **Admin** | Exam cell / IT staff | Create users and groups, see the audit log |
| **Teacher** | Faculty, TAs | Write questions, build and publish exams, grade, review proctoring, release results |
| **Student** | Examinees (adults) | Take exams, see released results |

### 1.4 Principles

1. **No lost work.** A saved answer is never lost, even on a bad connection.
2. **Every grade can be explained.** Scores are reproducible from stored data.
3. **AI flags, humans decide.** No automatic penalties from proctoring.
4. **Collect as little as possible.** No recordings; evidence images are deleted on a schedule.

---

## 2. Goals

Measured in our own testing before the final demo.

| ID | Goal | Target |
|---|---|---|
| G-01 | A teacher can build and publish a mixed exam (10 objective + 1 coding) without help | ≤ 30 min |
| G-02 | No lost answers when the network is cut and restored during an exam | 0 lost answers |
| G-03 | Run Code feedback is quick | ≤ 10 s, 95% of runs |
| G-04 | Coding submissions are graded quickly | ≤ 60 s, 95% of submissions, with 100 submitted together |
| G-05 | Hidden test cases never reach a student | 0 leaks (automated test) |
| G-06 | Proctoring is not noisy for honest students | ≤ 6 events per honest attempt (calibration runs) |
| G-07 | Proctoring catches staged cheating | ≥ 80% of staged incidents produce an event (calibration runs) |
| G-08 | Evidence is deleted on time | 0 evidence images past their deletion date |

---

## 3. Not in scope

| What | Why |
|---|---|
| Lockdown browser, screen recording, desktop agent | Not possible honestly from a web app |
| Live human proctoring / video streaming | Needs streaming infrastructure; conflicts with "no recordings" |
| AI grading of descriptive answers | Not reliable enough for marks |
| Automatic penalties from proctoring | Against principle 3 |
| Face recognition / ID verification | Different privacy class; needs separate consent |
| Students under 18 | Needs guardian consent flows |
| Mobile apps; exams on phones | Coding and proctoring need a desktop/laptop |
| Fully offline exams | Short disconnections are handled; offline exams are not |
| Custom checkers, interactive problems | Would run teacher code during grading — a second sandbox problem |
| LMS integration, SSO | Separate integration projects |
| Plagiarism detection | Separate system |
| MFA, multiple attempts per exam, per-student time overrides | Deferred (see § 8) |

---

## 4. User journeys

### Admin
1. **Set up.** Institution and first admin are created with the `platform-admin` CLI. Admin logs in and
   creates teachers and students (one by one or by CSV). Each receives an invitation email and sets a
   password.
2. **Groups.** Admin creates groups (e.g. "CSE-A 2026") and adds students, so teachers can assign exams to a
   whole group.
3. **Audit.** Admin filters the audit log by user, action or date to answer "who changed this?".

### Teacher
1. **Write an objective question.** Choose type, write the question (Markdown + images), set options and
   correct answer(s), points, optional negative marks, tags. Preview it as a student sees it.
2. **Write a coding question.** Statement, input/output format, constraints, examples; allowed languages
   with starter code; time and memory limits; test cases (public/hidden, weights); comparison mode. Add a
   reference solution and run **Validate**: the reference must pass every test case.
3. **Build an exam.** Add questions, set points and order, set the window and duration, navigation,
   shuffling, Run Code on/off, result release, proctoring mode and sensitivity. Assign groups or students.
   **Publish**: blocking problems are listed; once published, the exam is frozen.
4. **Monitor (should).** During the exam, see each student's status, progress, connection and event count.
   Extend time, force-submit or void an attempt (with a reason).
5. **Grade and release.** Objective and coding answers are graded automatically. Grade descriptive answers
   question-by-question, without student names shown. Release results.
6. **Review proctoring.** After an attempt ends, go through its events, look at the evidence images, and
   mark each `DISMISSED` or `FLAGGED` with a note.

### Student
1. **Dashboard.** See exams: available now, upcoming, completed.
2. **Before the exam.** Read instructions. For proctored exams: read and accept consent, then the device
   check (camera, microphone if needed, model download, connection test).
3. **Take the exam.** Timer always visible. Answer, flag for review, navigate. Save status always visible.
4. **Coding question.** Pick a language, write code, **Run** against sample tests, **Submit** for grading,
   see the verdict and which test cases passed (hidden ones show only pass/fail).
5. **Interruption.** Browser crash or network loss: reopen and continue; unsent answers are sent from the
   device. Time keeps running.
6. **Submit and results.** Submit (or auto-submit at time-up). See the result once released.

---

## 5. Functional requirements

Priority: **M** = must have (core demo), **S** = should have (if time allows).

### 5.1 Authentication — `AUTH`

| ID | Requirement | P |
|---|---|---|
| AUTH-01 | Login with email + password. Wrong email and wrong password give the same error | M |
| AUTH-02 | Accounts are created by an admin and activated through an invitation link (valid 7 days) where the user sets a password | M |
| AUTH-03 | Access token lasts 15 min; refresh token lasts 7 days, is rotated on each use, and reusing an old one logs out that whole session family | M |
| AUTH-04 | Logout, and "log out everywhere" | M |
| AUTH-05 | Password reset by email link (valid 1 h, single use). The response is the same whether or not the email exists. Reset logs out all sessions | M |
| AUTH-06 | 5 failed logins → account locked for 15 min. Login is rate-limited per IP | M |
| AUTH-07 | Password at least 10 characters; common passwords rejected; stored with Argon2 | M |

### 5.2 Roles and access — `ACC`

| ID | Requirement | P |
|---|---|---|
| ACC-01 | Three fixed roles: Admin, Teacher, Student. Full permission table in `SECURITY_AND_ACCESS.md` | M |
| ACC-02 | Each user belongs to one institution and can never see another institution's data. Asking for another institution's item returns "not found" | M |
| ACC-03 | Teachers can only edit their own questions and exams | M |
| ACC-04 | A question is **Private** (owner only) or **Institution** (other teachers can view, use in exams and copy, but not edit) | M |
| ACC-05 | Students can only see their own attempts and released results | M |

### 5.3 Users and groups — `USR`

| ID | Requirement | P |
|---|---|---|
| USR-01 | Admin creates, edits and deactivates users (name, email, role, roll number). Deactivated users cannot log in; their past work is kept | M |
| USR-02 | Admin creates groups and adds/removes students | M |
| USR-03 | CSV import of users: preview with per-row errors, then import valid rows; existing emails skipped | S |
| USR-04 | Admin can resend an invitation or trigger a password-reset email | M |

### 5.4 Question bank — `QB`

| ID | Requirement | P |
|---|---|---|
| QB-01 | Teachers list and search questions by text, type, tag and owner | M |
| QB-02 | **MCQ**: 2–10 options, exactly one correct | M |
| QB-03 | **MSQ**: 2–10 options, one or more correct; scoring `ALL_OR_NOTHING` (default) or `PARTIAL` | M |
| QB-04 | **True/False**: two fixed options | M |
| QB-05 | **Descriptive**: free-text answer, optional max length, rubric visible only to graders, graded by hand | M |
| QB-06 | Question text supports Markdown, code blocks and images. All content is sanitised | M |
| QB-07 | **Versioning**: editing a question used in a published exam creates a new version; published exams keep the old one | M |
| QB-08 | **Preview** shows exactly what a student will see | M |
| QB-09 | Questions can be copied and archived | M |

### 5.5 Coding questions — `CQ`

| ID | Requirement | P |
|---|---|---|
| CQ-01 | Fields: statement, input format, output format, constraints, examples | M |
| CQ-02 | Languages: C++17, Java 21, Python 3.12, Node.js 22. Teacher picks which are allowed and can give starter code for each | M |
| CQ-03 | Limits: time 100–10,000 ms, memory 16–512 MB. Each language has a time multiplier (e.g. Java, Python are given more time) | M |
| CQ-04 | Test cases: up to 50, each with input, expected output (≤ 1 MB each), weight (whole number ≥ 1), public or hidden. At least one hidden test case is required | M |
| CQ-05 | Public test cases are shown to students in full. **Hidden test cases are never shown or sent to a student** — not input, output, or timings | M |
| CQ-06 | Output comparison mode (see § 6.2), default `TRIM` | M |
| CQ-07 | Partial scoring on/off (default on); max submissions per student (default 10); Run Code allowed on/off | M |
| CQ-08 | **Validate**: teacher adds a reference solution in at least one allowed language; it must pass every test case. The report shows time per case and warns if any case uses > 50% of the time limit. A coding question can't be published without a passing validation | M |
| CQ-09 | Editing test cases after validation marks the question "needs validation" again | M |

### 5.6 Exams — `EX`

| ID | Requirement | P |
|---|---|---|
| EX-01 | Create, edit, delete (only if no attempts exist) and archive exams | M |
| EX-02 | Add questions from the bank, set order, points and negative marks per question | M |
| EX-03 | Settings: see § 6.3 | M |
| EX-04 | Assign to groups and/or individual students. Only assigned students can see or start the exam | M |
| EX-05 | **Publish check** lists blocking problems and warnings (§ 6.4). Publishing is refused while any block exists | M |
| EX-06 | **Publish freezes the exam**: questions and versions pinned, settings locked. Only the window end time can still be extended, and assignments added | M |
| EX-07 | Teacher can take a **preview attempt** of their own exam; it is marked as a test and excluded from results | M |
| EX-08 | Exam list with status (Draft, Published, Archived) and window state (Upcoming, Open, Closed) | M |

### 5.7 Taking an exam — `ATT`

| ID | Requirement | P |
|---|---|---|
| ATT-01 | A student can start if: exam published, window open (server time), assigned, no existing attempt, consent given (if proctored), and at least 5 min of the window remain | M |
| ATT-02 | One attempt per student per exam. If a teacher voids an attempt, the student may start again | M |
| ATT-03 | **Deadline** = the earlier of start + duration (+ any extension) and the window close. Fixed at start, stored on the server | M |
| ATT-04 | **Timer** is shown from the server's deadline and server time. Changing the computer's clock has no effect | M |
| ATT-05 | Shuffling (if on) of questions and/or options is fixed per student, so a reload shows the same order | M |
| ATT-06 | Navigation: **Free** (any order) or **Sequential** (forward only, no going back) | M |
| ATT-07 | Mark for review; clear an answer; question palette shows answered / unanswered / marked | M |
| ATT-08 | **Autosave**: answers are saved to the device first, then sent to the server in batches every 2–3 s. Save status is always visible | M |
| ATT-09 | **Resume**: after a crash, reload or device restart, the student continues with the same questions, order, answers and deadline | M |
| ATT-10 | **Submit**: shows a summary (answered, unanswered, marked) and asks to confirm. Submitting twice is harmless | M |
| ATT-11 | **Auto-submit** at the deadline, even if the browser is closed. Answers arriving more than 60 s after the deadline are rejected | M |
| ATT-12 | Weak or lost connection handled as in § 6.6 | M |

### 5.8 Code execution — `EXE`

| ID | Requirement | P |
|---|---|---|
| EXE-01 | Student picks a language from the allowed list; drafts are kept per language, so switching doesn't lose code | M |
| EXE-02 | **Run Code** runs against public test cases and shows input, expected output, actual output and pass/fail. Limit: one run per 8 s, 20 per question. Says clearly "does not affect your score" | M |
| EXE-03 | **Run with custom input**: student types input and sees the output, no comparison | S |
| EXE-04 | **Submit Code** grades against all test cases. Shows verdict, score, and passed/total; public cases in full, hidden cases as pass/fail only. At least 5 s between submissions | M |
| EXE-05 | Submission history per question, showing which submission counts (`BEST` default, or `LAST`, set on the exam) | M |
| EXE-06 | At the end of an attempt, if the last saved draft is newer than the last submission, it is submitted and graded automatically (doesn't count toward the limit) | M |
| EXE-07 | Submissions are never dropped when the system is busy; they wait in the queue. Run Code may be slowed down first | M |
| EXE-08 | If the platform fails to run a submission (not the student's code), it gets no score, is marked `INTERNAL_ERROR`, and the teacher can re-run it | M |
| EXE-09 | **Re-evaluate**: teacher re-runs submissions for a question (e.g. after fixing a test case); changed released scores are recorded and the student is notified | S |

### 5.9 Grading and results — `GRD`

| ID | Requirement | P |
|---|---|---|
| GRD-01 | Objective answers are graded automatically on submit (§ 6.1) | M |
| GRD-02 | Coding answers are scored from the counted submission (§ 6.2) | M |
| GRD-03 | Descriptive answers are graded by the teacher: a grading screen grouped by question, student names hidden by default, mark from 0 to points, optional feedback | M |
| GRD-04 | Each attempt shows a grading status: Pending, Awaiting coding, Awaiting manual, Complete | M |
| GRD-05 | Result: total, percentage, pass/fail (if a pass mark is set), per-question scores | M |
| GRD-06 | Release: **Manual** (default) or **On submit** (only allowed if the exam has no descriptive questions). Results can only be released once grading is complete | M |
| GRD-07 | Student result view: total, per-question scores, coding verdicts and passed counts, teacher feedback, integrity outcome. Never hidden test case content or proctoring events | M |
| GRD-08 | Changing a released score records old score, new score, reason, who, and notifies the student | M |
| GRD-09 | Student sees a history of their past exams and released results | M |

### 5.10 Proctoring — `PRC`

| ID | Requirement | P |
|---|---|---|
| PRC-01 | Per exam mode: **Off**, **Video**, or **Video + Audio** | M |
| PRC-02 | Teacher picks sensitivity (Relaxed / Standard / Strict) and switches gaze and book detection on/off (§ 6.5) | M |
| PRC-03 | **Consent**: before a proctored exam the student sees what is collected, why, how long it is kept and who sees it, and must accept. Declining means they can't take that exam. Each decision is recorded | M |
| PRC-04 | **Device check**: camera works and a face is visible; microphone works (Video + Audio); AI models downloaded; connection tested. Camera/mic/models must pass to start; a weak connection only warns | M |
| PRC-05 | **No video leaves the device.** Detection runs in the browser; only events with up to 3 still images (and periodic spot-check frames) are uploaded | M |
| PRC-06 | Detectors, thresholds and severities as in § 6.5 | M |
| PRC-07 | The server re-checks every event with images; it sets severity and confidence, and rejects events it can't confirm. The browser's opinion never sets severity | M |
| PRC-08 | Audio is never uploaded or stored; voice events are metadata only | M |
| PRC-09 | Students are never shown events, severity or confidence during or after the exam | M |
| PRC-10 | **Review**: after an attempt ends, the teacher sees its events in time order with images, and marks each `DISMISSED` or `FLAGGED` with a note. Viewing evidence is audit-logged | M |
| PRC-11 | **Integrity Outcome** per attempt: Pending review (any unreviewed event), No concerns (none flagged), Concerns confirmed (at least one flagged). Shown next to the score, never changes it | M |
| PRC-12 | Teachers can bulk-dismiss LOW and MEDIUM events; HIGH events must be reviewed one by one | S |
| PRC-13 | Evidence images are deleted automatically 30 days (institution setting, 7–90) after the exam window closes. Event records without images are kept | M |
| PRC-14 | If proctoring breaks (camera lost, models crash), the exam continues; the problem is recorded as an event for the teacher | M |
| PRC-15 | Per-detector dismissal rates are shown to teachers, so noisy detectors are visible | S |

### 5.11 Monitoring and analytics — `MON`

| ID | Requirement | P |
|---|---|---|
| MON-01 | Live monitor (refreshes every 10 s): per student — not started / in progress / submitted, answered count, time left, connection (online / weak / offline), pending answers, event count | S |
| MON-02 | From the monitor: extend time, force-submit, void (reason required, audit-logged) | M (actions) / S (screen) |
| MON-03 | Exam analytics: average, median, highest, lowest, score histogram, pass rate | S |
| MON-04 | Question analytics: average score, % fully correct, option-pick counts for MCQ/MSQ | S |
| MON-05 | Coding analytics: verdict counts and **pass rate per test case** (finds broken hidden tests) | S |

### 5.12 Notifications — `NOT`

| ID | Requirement | P |
|---|---|---|
| NOT-01 | Emails: invitation, password reset | M |
| NOT-02 | In-app notifications: exam assigned, result released, result changed; unread count in the header | S |
| NOT-03 | Email for result released | S |

### 5.13 Audit log — `AUD`

| ID | Requirement | P |
|---|---|---|
| AUD-01 | Append-only log: who, what, which item, when, from where, what changed | M |
| AUD-02 | Logged actions include: login failures and lockouts, user changes, exam publish/edit/archive, time extension, force-submit, void, mark changes, result release and changes, evidence viewed, review decisions, re-evaluation | M |
| AUD-03 | Admin can search the log by user, action, item and date | M |

---

## 6. Rules in detail

### 6.1 Objective scoring

| Type | Correct | Wrong | Not answered |
|---|---|---|---|
| MCQ, True/False | + points | − negative marks | 0 |
| MSQ `ALL_OR_NOTHING` | + points if exactly the correct set | − negative marks | 0 |
| MSQ `PARTIAL` | points × (correct picked ÷ total correct), if no wrong option picked | − negative marks if any wrong option picked | 0 |

Order: score each question → round to 2 decimals (half up) → add up → total can't go below 0 → percentage.

### 6.2 Coding scoring

**Output comparison** (applied to both expected and actual output):

| Mode | Rule |
|---|---|
| `EXACT` | Byte-for-byte equal |
| `TRIM` (default) | Same after normalising line endings and removing trailing spaces on each line and trailing blank lines |
| `TOKEN` | Same sequence of words/numbers, ignoring how whitespace is laid out |
| `NUMERIC` | Like `TOKEN`, but numbers match within 1e-6 (absolute or relative) |

**Score** for a question worth `P` points, with total test case weight `W` and passed weight `w`:
1. Compile error → 0.
2. Partial scoring off → `P` if every test case passes, else 0.
3. Partial scoring on → `P × w ÷ W`, rounded to 2 decimals.
4. A test case that fails for any reason (wrong output, timeout, memory, crash, too much output) adds 0.
5. No negative marks on coding questions.
6. Platform failure → no score (`INTERNAL_ERROR`), never 0.

Example: `P = 10`, weights `1,1,2,2,2,2,3,3` (`W = 16`); passes all but the two weight-3 cases → `w = 10` →
score `6.25`, verdict `PARTIAL`.

**Verdict**: `ACCEPTED` (all pass), `PARTIAL` (some pass, partial on), otherwise the main reason it failed —
`WRONG_ANSWER`, `COMPILE_ERROR`, `RUNTIME_ERROR`, `TIME_LIMIT_EXCEEDED`, `MEMORY_LIMIT_EXCEEDED`. The verdict
is for display; the score always comes from the rules above.

### 6.3 Exam settings

| Setting | Default |
|---|---|
| Window open / close | Required |
| Duration (minutes) | Required |
| Navigation | Free |
| Shuffle questions / options | Off / Off |
| Run Code enabled | On |
| Counted coding submission | `BEST` |
| Pass mark (%) | None |
| Result release | Manual |
| Proctoring mode | Off |
| Proctoring sensitivity | Standard |
| Gaze detection / book detection | Off / Off |
| Consent text | The exam's own text, else the institution's default, else the standard text (covers § 8.2 of the security doc). Editable |

Fixed for everyone (not settings): 60 s grace after the deadline, scores rounded to 2 decimals, totals never
below 0.

### 6.4 Publish check

| Blocks publishing | Warning only |
|---|---|
| No questions, or total points = 0 | A question worth 0 points |
| Window in the past, or close before open | Duration very short for the number of questions |
| Duration longer than the window | Descriptive question without a rubric |
| No students assigned | Coding question with no public test cases |
| Coding question without a passing validation | Shuffle on with Sequential navigation |
| Proctored exam without consent text | |

### 6.5 Proctoring detectors

The guiding rule: **a false alarm costs more than a missed one.** Thresholds sit just above what honest
students do naturally. Values below are for the **Standard** sensitivity.

| Event | Fires when | Severity | Default |
|---|---|---|---|
| `FACE_ABSENT` | No face for ≥ 5 s | 5–15 s LOW · 15–60 s MEDIUM · > 60 s HIGH | On |
| `MULTIPLE_FACES` | A second face (≥ 20% of the main face's size) for ≥ 2 s | < 5 s MEDIUM · ≥ 5 s HIGH | On |
| `GAZE_AWAY` | Head turned left/right > 35° or up > 25° for ≥ 8 s. Looking down is ignored | 8–30 s LOW · > 30 s MEDIUM | Off |
| `TAB_SWITCH` | Tab hidden or window unfocused ≥ 2 s, or fullscreen exited | < 10 s LOW · 10–60 s MEDIUM · > 60 s HIGH. 5th+ switch at least MEDIUM | On |
| `VOICE_DETECTED` | Speech in ≥ 50% of a 10 s window (Video + Audio only) | LOW · ≥ 20 s MEDIUM | On in Video + Audio |
| `PHONE_DETECTED` | Spot-check frame: phone found with confidence ≥ 0.70 | 0.70–0.85 MEDIUM · ≥ 0.85 HIGH | On |
| `BOOK_DETECTED` | Spot-check frame: book found with confidence ≥ 0.70 (for closed-book exams) | LOW | Off |
| `SIGNAL_LOST` | Heartbeats arrive but proctoring has stopped for ≥ 60 s | MEDIUM · > 5 min HIGH | On |

**Rules for all detectors**

| Rule | Value |
|---|---|
| Settling time | No camera events in the first 60 s (except multiple faces) |
| Merge | Same event type again within 10 s → extends the existing event |
| Cooldown | Same type not raised again for 60 s after an event ends |
| Server check | Confidence < 0.6 → severity drops one level; nothing found → event rejected |
| Evidence | 3 images per event (start, middle, latest) |
| Evidence limit | 30 events with images per attempt; later events have no images |
| Frame rate | 3 fps, down to 1 fps on slow devices; thresholds are in seconds |
| Spot checks | One random frame every 20–40 s |

**Sensitivity presets** multiply all time thresholds: Relaxed × 1.5, Standard × 1.0, Strict × 0.6.

**Calibration**: before the final demo, the team runs honest and staged-cheating mock exams, counts false
and missed alarms per detector, and tunes these numbers. The results go into the project report.

### 6.6 Weak connections

| Situation | Behaviour |
|---|---|
| Before the exam | Device check downloads the AI models and editor files and tests the connection. Weak connection → warning only |
| During the exam | Answers are kept on the device and sent when possible; answers go before proctoring uploads. Status shows *All saved* / *Saving…* / *Offline — N answers saved on this device*. The student is never blocked |
| Timer | Keeps running while offline. The teacher sees disconnection time and can extend the attempt |
| After the deadline | Answers arriving more than 60 s late are rejected; the student is told which changes were not saved |
| Unsubmitted code | Last saved draft is graded automatically (EXE-06) |
| Proctoring | A lost connection is never treated as cheating. Queued evidence can finish uploading up to 30 min after the attempt |

---

## 7. Non-functional requirements

Targets for a single server (8 CPU cores, 16 GB RAM) unless stated.

| ID | Area | Requirement |
|---|---|---|
| NFR-01 | Hard rule | An answer the server confirmed as saved is never lost |
| NFR-02 | Hard rule | Hidden test cases never appear in any student response (automated test) |
| NFR-03 | Hard rule | Student code has no network access and cannot reach other submissions or platform services |
| NFR-04 | Capacity | 200 students taking an exam at the same time |
| NFR-05 | Speed | Save answer / heartbeat: 95% under 300 ms. Pages: 95% under 1 s |
| NFR-06 | Speed | Exam page usable within 3 s on a 10 Mbps connection (after the device check has cached the large files) |
| NFR-07 | Browser load | In-browser proctoring uses ≤ 30% of one CPU core on a typical student laptop |
| NFR-08 | Browsers | Latest two versions of Chrome, Edge and Firefox, on desktop/laptop |
| NFR-09 | Security | HTTPS in deployment; all input validated on the server; secrets only in `.env` (never committed). Details in `SECURITY_AND_ACCESS.md` |
| NFR-10 | Privacy | No recordings; no audio stored; evidence deleted on schedule; student images never sent to third-party services |
| NFR-11 | Accessibility | The exam works fully with the keyboard; status is never shown by colour alone; the timer and save status can be read by screen readers |
| NFR-12 | Reliability | Every background job can safely run twice; if Redis restarts, nothing permanent is lost and stuck jobs are re-queued |
| NFR-13 | Backups | Nightly database and file backups, kept 7 days; restore tested once |
| NFR-14 | Code quality | Scoring, comparison and timer logic unit-tested; every API endpoint has tests including "not allowed" cases; CI runs on every push |

---

## 8. Scope

### 8.1 Must have (core demo)

Login, roles, invitations · question bank with all five types and versioning · coding questions with
hidden tests and validation · exam build, publish, freeze, assign · exam taking with server timer,
autosave, resume, auto-submit · Run Code and Submit Code in four languages · automatic and manual grading,
result release · proctoring with consent, device check, detectors, server check, teacher review, integrity
outcome · audit log · emails for invitation and password reset.

### 8.2 Should have (if time allows)

Live monitor screen · analytics · CSV import · re-evaluation · custom-input runs · in-app notifications and
result emails · bulk dismiss · detector dismissal rates.

The evidence deletion job is **must** (PRC-13), not should: the privacy promise depends on it.

### 8.3 Later

MFA · multiple attempts per exam · per-student time overrides (accessibility) · answer-key reveal ·
result export (CSV) · question import/export · session list · plagiarism detection · LMS/SSO.

---

## 9. Risks

| Risk | Impact | What we do |
|---|---|---|
| Sandbox escape or abuse (fork bombs, infinite output) | High | Strict container limits, no network, one container per test case; tests for each attack type |
| Hidden test case leak | High | Separate student views; automated leak test in CI |
| Proctoring false alarms flood teachers | High | Conservative thresholds, server re-check, calibration runs, noisy detectors off by default |
| Proctoring unfair to some students (lighting, skin tone, glasses, disability) | High | Human review always; dismissal rates per detector; calibration with varied people and lighting |
| Student laptops too slow for in-browser AI | Medium | Frame rate drops to 1 fps; device check warns early |
| Weak college Wi-Fi on exam day | Medium | Offline-safe autosave, prefetching, teacher time extensions |
| Server overloaded by many submissions at the end | Medium | Queue never drops submissions; Run Code slowed first |
| Team runs out of time | Medium | Must/Should split; build order in `FEATURE_TICKETS.md` |

## 10. Assumptions

- All students are adults and use a laptop or desktop with a webcam.
- The demo runs on one Linux machine (or WSL2) with Docker; a GPU is optional.
- One institution is enough for the demo, but the system supports several.
- The demo uses mock exams taken by the team and volunteers; no real students' data.
- The college provides HTTPS and an SMTP account if deployed for real.

## 11. Open questions

| # | Question |
|---|---|
| OQ-1 | Which machine hosts the final demo, and does it have a GPU? (Affects inference speed) |
| ~~OQ-2~~ | ~~Real exam or mock exams?~~ **Decided 2026-10-24: mock exams only.** No real student data is collected; consent text and data handling are still built as specified |
| ~~OQ-3~~ | ~~Default consent text — who writes and approves it?~~ **Decided 2026-10-30:** Xaminer ships a standard text covering every point of SECURITY § 8.2 (`app/platform/consent.py`); an admin can replace it for the institution, a teacher for one exam |
