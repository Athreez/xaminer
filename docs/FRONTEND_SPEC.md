# Frontend Specification — CBT Platform with AI Proctoring and Automated Coding Evaluation

| Field | Value |
|---|---|
| Document | 4 of 5 — Frontend Specification |
| Status | Draft v0.2 — under review |
| Last updated | 2026-10-24 |
| Code | None yet. This document comes first. |

**This document owns:** routes, pages, screen layouts, UI state names and status labels. Features and rules
come from `PRD.md`; API and data from `TECHNICAL_ARCHITECTURE.md`; permissions from
`SECURITY_AND_ACCESS.md`.

---

## 1. Principles

| Principle | What it means in the UI |
|---|---|
| **The exam gets the student's full attention** | The exam screen has no sidebar, menus, notifications or animations. Only the question, navigator, timer and status |
| **State is always visible** | The student never has to guess if an answer saved, how much time is left, or if they are online |
| **Honest waiting** | Show the real state (Queued / Running / Done), never a spinner that pretends it is nearly finished |
| **AI output is not a verdict** | Proctoring words: "detected", "for review", "flagged as a concern by a teacher". Never "violation" or "cheating" |
| **Errors explain the fix** | Every error says what happened and what to do next. No dead ends |
| **Accessible by default** | Keyboard works everywhere; status is never shown by colour alone |
| **The UI is not the security** | Hiding a button is for convenience; the server enforces every rule |

---

## 2. Frontend architecture

### 2.1 Stack

Vite + React 19 + TypeScript 5.9 · React Router 7 · TanStack Query · Zustand · `idb` (IndexedDB) ·
Tailwind CSS 4 + shadcn/ui (Radix-based; `cn()` = `clsx` + `tailwind-merge`) · CodeMirror 6 · MediaPipe
Tasks Vision · `react-markdown` + sanitiser · `openapi-fetch` client typed from the backend's OpenAPI spec
(`make api-client`).

Imports use the `@/` alias for `src/`. shadcn components live in `src/components/ui/` and are added with
`npx shadcn@4.22.1 add <name>` (version pinned: the unpinned `npx shadcn@latest` hits an npm 11.6 bug).

### 2.2 Folder structure

```
/frontend/src
  api/            openapi.json + schema.d.ts (generated), client.ts (typed client, error type)
  auth/           Login state, token refresh, role-based route guard
  components/     Shared UI: ui/ (shadcn), layout/ (AppShell), StatusPill, Countdown, ...
  features/
    admin/        Users, groups, audit log, settings
    questions/    Question bank and editors
    exams/        Exam builder, publish, monitor, grading, results, analytics
    review/       Proctoring review
    student/      Dashboard, instructions, pre-check, results
    runner/       The exam screen (see § 6)
    system/       Home, error pages, placeholders
    proctoring/   Camera, MediaPipe worker, detectors, uploader
  lib/            Markdown renderer, time sync, IndexedDB outbox
  routes.tsx
```

### 2.3 Key mechanisms

| Mechanism | How |
|---|---|
| Server data | TanStack Query for all fetching and polling. Polling interval comes from the server's `poll_after_ms` |
| Auth | Access token kept in memory. On `401` the wrapper calls `/auth/refresh` (the cookie is sent automatically) and retries the request. Only one refresh runs at a time across all tabs (Web Locks API, `navigator.locks`); on `TOKEN_ALREADY_ROTATED` it retries the refresh once. Any other refresh failure → `SESSION_EXPIRED` |
| Route guards | Each route declares its role; wrong role → `/403`. The server checks again anyway |
| Exam state | Zustand store for the runner: answers, current question, flags, timer offset, connection status |
| Outbox | IndexedDB queue of unsent answers, drafts and proctoring uploads. Survives reload and crash. One uploader sends in priority order: answers/drafts → heartbeat → code run/submit → proctoring events → spot checks |
| Time sync | `offset = server_time − Date.now()` from every attempt response; remaining = `deadline_at − (Date.now() + offset)` |
| Proctoring | MediaPipe runs in a **Web Worker** so the exam screen stays responsive. Detectors produce events; the uploader sends them |
| Caching | A Service Worker caches MediaPipe models, WASM files and editor language modes during the pre-check |
| Markdown | One shared renderer (`react-markdown` + sanitiser) for all question text and feedback |

---

## 3. Design system

### 3.1 Theme

Decided 2026-10-27 from reference screenshots the team supplied: **dark-first navy surfaces, an emerald
→ cyan brand gradient, blue for "selected", tinted status colours, large rounded cards.** Calm and
clean, no decoration. The palette lives in `frontend/src/index.css`; the live style guide is at
**`/theme`**.

| Item | Rule |
|---|---|
| Light / dark | Both. Follows the device setting, with a toggle (device → light → dark) saved per browser. **Proctored exam screens are always light**: in a dim room the screen lights the student's face, and a dark screen causes false "face not visible" events (`forceLightTheme()` in `src/lib/theme.ts`) |
| Font | System font stack (Segoe UI / San Francisco / Roboto): nothing to download on weak connections. Monospace for code, timer and scores |
| Shape | Radius 12 px; cards 16 px; buttons 10 px. Thin borders plus `shadow-card` (light: soft drop shadow; dark: faint top highlight + deep shadow); brand elements get a soft glow (`shadow-glow`) |
| Spacing | Tailwind's 4 px scale only |
| Focus | Visible focus ring on every interactive element, never removed |
| Motion | Minimal; disabled under `prefers-reduced-motion` |

**Palette** (every text/background pair checked against WCAG AA):

| Role | Dark | Light | Used for |
|---|---|---|---|
| Background | `#0B1221` + violet (bottom-right) and faint emerald (top-left) glows | `#F3F6FB` + faint emerald and sky glows | Page |
| Card | `#121B2F`, border `#2A3650` | `#FFFFFF`, border `#E3E8F0` | Cards, rows, panels |
| Text / muted text | `#F1F5F9` / `#94A3B8` | `#0F172A` / `#475569` | |
| **Brand** | gradient `#10B981 → #06B6D4`, **near-black text** `#022C22` | gradient `#047857 → #0369A1` (emerald → sky), white text | Main buttons, icon tiles |
| Brand headings | gradient `#34D399 → #22D3EE` | gradient `#059669 → #0284C7` | `text-brand-gradient`, **large headings only** (light shades pass 3:1 for large text, not 4.5:1 for body text) |
| **Selection** | `#3B82F6` border on blue tint | `#2563EB` border on `#EFF6FF` | Chosen answer, current question |
| Progress | gradient `#2563EB → #7C3AED`, white text | same | Progress bars, "Next" |
| Success | `#34D399` on green tint | `#047857` on `#ECFDF5` | Passed, answered |
| Warning | `#FBBF24` on amber tint | `#B45309` on `#FFFBEB` | Warnings |
| Danger | text `#F87171` on red tint; buttons solid `#DC2626` | `#DC2626` on `#FEF2F2`; buttons solid `#DC2626` | Failed, errors; destructive buttons always solid red with white text (4.8:1) |

**Changed from the screenshots on purpose:**

- *White text on the bright green/cyan buttons* reads at about 2.5:1 (AA needs 4.5:1). Dark mode keeps
  the bright gradient with near-black text (6:1); light mode uses deeper shades with white text (5.4:1).
- *The pop-up "Warning 2/8: Suspicious hand gesture detected"* is not copied: students are never told
  about detections during the exam (§ 8.2, PRD PRC-09), and a modal pop-up would interrupt the exam.
- *Status by colour only* (e.g. green/blue/grey question numbers) gets shapes and text as well (§ 6.4).

### 3.2 Shared components

| Component | Notes |
|---|---|
| `Button` | Primary / secondary / ghost / danger. Loading state keeps its width and disables the button |
| Form fields | Always a visible label (never placeholder as label); errors shown under the field and linked for screen readers |
| `Table` | Sorting, cursor pagination, empty and "no results for these filters" states |
| `Modal`, `Drawer`, `Tabs` | shadcn/Radix versions (focus handled) |
| `StatusPill` | Text + icon + colour, never colour alone |
| `SeverityBadge` | LOW / MEDIUM / HIGH with different shapes. Tooltip: "Severity reflects how the detector is configured, not a finding" |
| `Countdown` | Server-synced timer (§ 6.3) |
| `SaveStatus`, `ConnectionStatus` | Exam header indicators (§ 6.3) |
| `QuestionNavigator` | Question grid (§ 6.4) |
| `CodeEditor` | CodeMirror 6 wrapper: language mode, line numbers, bracket matching, auto-indent, search. `Esc` then `Tab` leaves the editor |
| `MarkdownView` | The shared sanitising renderer |
| `TestCaseResults` | Per-case rows; details only for public cases (§ 7.4) |
| `EvidenceViewer` | 3-image strip with timestamps, keyboard navigation, no download button |
| `Stepper` | Pre-check steps and exam builder steps |
| `EmptyState`, `ErrorState` | Heading, one-line reason, one action |
| `Toast` | Short confirmations only. **Never used in the exam screen** |

### 3.3 Status labels

One label per state, used everywhere.

| Thing | Labels |
|---|---|
| Exam | Draft · Published · Archived; window: Upcoming · Open · Closed |
| Attempt (teacher view) | Not started · In progress · Submitted · Auto-submitted · Voided |
| Grading | Pending · Awaiting code evaluation · Awaiting marking · Complete |
| Result | Not released · Released |
| Question in navigator | Not visited · Not answered · Answered · Marked for review · Answered & marked |
| Code run / submission | Queued · Running · Done · Failed (our side) |
| Verdict | Accepted · Partially correct · Wrong answer · Compilation error · Runtime error · Time limit exceeded · Memory limit exceeded · Could not be evaluated |
| Proctoring event (teacher) | Checking · Ready for review · Dismissed · Flagged as a concern |
| Integrity outcome (teacher) | Pending review · No concerns · Concerns confirmed |
| Integrity outcome (student) | "No concerns were raised" · "Your teacher confirmed a concern during this exam" (shown only on a released result; if still pending, nothing is shown) |
| Connection (teacher monitor) | Online · Weak · Offline |

### 3.4 Writing rules

| Rule | Example |
|---|---|
| Say the cause and the fix | "This file is 3 MB. The limit is 1 MB." |
| Don't blame the student for our failure | "We couldn't run your submission. This is a problem on our side. Your code is saved and will be re-run. It will not be scored zero." |
| State consequences before irreversible actions | "Publishing freezes this exam's questions and settings. 60 students will be able to see it." |
| Numbers always have context | "6.25 / 10 — 6 of 8 test cases passed" |
| Honest waiting | "Queued — 12 ahead of you", not a bare spinner |

---

## 4. Routes

| Route | Role | Page |
|---|---|---|
| `/login` | — | Sign in |
| `/activate#token=…` | — | Set password from invitation (token after `#`, never in the path) |
| `/forgot-password` · `/reset-password#token=…` | — | Password reset (token after `#`) |
| `/` | any | Redirect to the role's home |
| `/admin/users` · `/admin/users/:userId` | Admin | Users |
| `/admin/users/import` | Admin | CSV import (S) |
| `/admin/groups` · `/admin/groups/:groupId` | Admin | Groups |
| `/admin/exams` | Admin | Exam list (title, dates, status only) |
| `/admin/settings` | Admin | Institution settings: evidence retention days, default consent text |
| `/admin/audit` | Admin | Audit log |
| `/teacher` | Teacher | Dashboard |
| `/teacher/questions` | Teacher | Question bank |
| `/teacher/questions/new` · `/teacher/questions/:id` | Teacher | Question editor (all types) |
| `/teacher/questions/:id/preview` | Teacher | Student-view preview |
| `/teacher/exams` · `/teacher/exams/new` | Teacher | Exam list, create |
| `/teacher/exams/:examId` | Teacher | Exam overview |
| `/teacher/exams/:examId/questions` | Teacher | Add and order questions |
| `/teacher/exams/:examId/settings` | Teacher | Settings, including proctoring |
| `/teacher/exams/:examId/students` | Teacher | Assign groups / students |
| `/teacher/exams/:examId/publish` | Teacher | Publish check and publish |
| `/teacher/exams/:examId/monitor` | Teacher | Live monitor (S) |
| `/teacher/exams/:examId/grading` | Teacher | Grade descriptive answers |
| `/teacher/exams/:examId/results` | Teacher | Results and release |
| `/teacher/exams/:examId/results/:attemptId` | Teacher | One student's attempt in detail |
| `/teacher/exams/:examId/review` | Teacher | Proctoring review list |
| `/teacher/exams/:examId/review/:attemptId` | Teacher | One student's event timeline |
| `/teacher/exams/:examId/analytics` | Teacher | Analytics (S) |
| `/student` | Student | Dashboard |
| `/student/exams/:examId` | Student | Instructions |
| `/student/exams/:examId/precheck` | Student | Consent and device check (proctored exams) |
| `/student/results` · `/student/results/:attemptId` | Student | Released results |
| **`/attempt/:attemptId`** | Student, Teacher (preview) | **The exam screen** |
| `/notifications` | any | Notifications (S) |
| `/account` | any | Change password, log out everywhere |
| `/403` · `/404` | any | Error pages |

**Layout per role**

| Role | Navigation |
|---|---|
| Admin | Left sidebar: Users · Groups · Exams · Settings · Audit log |
| Teacher | Left sidebar: Dashboard · Questions · Exams. Inside an exam, a tab bar: Overview · Questions · Settings · Students · Publish · Monitor · Grading · Results · Review · Analytics |
| Student | Top bar: Dashboard · Results |
| **Exam screen** | **No app navigation at all.** Only the exam header and content |

Header outside the exam screen: institution name, notifications bell (S), user menu.

---

## 5. Pages

### 5.0 Login

Email and password. On `INVALID_CREDENTIALS`: "Email or password is incorrect." On `ACCOUNT_LOCKED`: the
time it unlocks. On `INSTITUTION_REQUIRED`: a list of the institutions from the error's `details`; picking
one repeats the login with that `institution_id`. After login, go to the role's home.

Activation (`/activate`): read the token from the `#` part, call `POST /auth/invite/inspect` to show
"Welcome, Ravi Kumar (ABC College)", then a new-password form (`/auth/invite/accept`). Weak-password
errors appear under the field and the link stays usable. `INVALID_TOKEN`: "This link is invalid or has
expired. Ask your admin for a new invitation." Password reset pages work the same way.

### 5.1 Admin

| Page | Contents |
|---|---|
| Users | Table: name, email, role, roll no., status. Filters: role, status, search. Actions: add user (sends invite), edit, deactivate, resend invite, send password reset |
| CSV import (S) | Upload → preview with per-row errors → import valid rows → summary (imported / skipped / failed) |
| Groups | List of groups with member count; group page to add/remove students (search + multi-select) |
| Exams | Read-only list: title, owner, window, status |
| Settings | Evidence retention days (7–90), default consent text. Shows "Overdue evidence deletions: 0" (anything else shown as an error) |
| Audit log | Table: time, user, action, item, details. Filters: user, action, date range |

### 5.2 Teacher — questions

| Page | Contents |
|---|---|
| Question bank | Table: title (first line), type, tags, owner, visibility, used in N exams. Filters: type, tag, owner (mine / shared), search. Actions: new, edit, copy, archive |
| Question editor | Type picker, then: Markdown text with preview, images upload, points, negative marks, tags, visibility. MCQ/MSQ/TF: options with "correct" toggles, MSQ scoring mode. Descriptive: max length, rubric. If the question is used in a published exam, a banner: "Saving creates a new version. Published exams keep the old one." |
| Coding editor | See § 5.3 |
| Preview | Exactly the student view, with a "Preview" label |

### 5.3 Teacher — coding question editor

Tabs: **Problem** · **Languages & limits** · **Test cases** · **Validate**.

| Tab | Contents |
|---|---|
| Problem | Statement, input format, output format, constraints, examples (Markdown) |
| Languages & limits | Checkboxes for C++17 / Java 21 / Python 3.12 / Node 22, with starter code editor per language. Time limit, memory limit, with each language's effective limit shown (multiplier). Comparison mode with a one-line explanation of each. Partial scoring, max submissions, Run Code allowed |
| Test cases | Table: #, label, public/hidden, weight, input size, output size. Add/edit in a drawer with two text areas. "Add from examples" button. Total weight shown. Warning if no hidden case (publishing is blocked) |
| Validate | Reference solution editor (pick language) → **Validate**. Result: per case pass/fail, time and memory, with a warning icon on any case using > 50% of the time limit. Status badge: Not validated / Passed / Failed / Needs re-validation |

### 5.4 Teacher — exams

| Page | Contents |
|---|---|
| Exam list | Title, status, window state, students, has coding, proctoring mode. Actions: new, open, archive |
| Overview | Status, window, counts (assigned / started / submitted / graded), shortcuts to the next action (e.g. "3 answers need marking") |
| Questions | Left: question bank picker with search. Right: exam's questions with drag-to-reorder, points, negative marks; total points |
| Settings | All settings from PRD § 6.3, grouped: Schedule · Navigation · Coding · Results · Proctoring (mode, sensitivity, gaze on/off, books on/off, consent text). Locked after publish except window end |
| Students | Assign groups or individual students; list of assigned students |
| Publish | Run check → list of blocks (each linked to the setting or question to fix) and warnings. Publish confirmation summarises questions, points, students, window, proctoring. Also "Take a preview attempt" |
| Monitor (S) | Table refreshed every 10 s: student, status, answered / total, time left, connection (Online / Weak / Offline), unsynced answers, event count. Row actions: extend time, force-submit, void (all ask for a reason) |
| Grading | Pick a descriptive question → one answer at a time, student name hidden ("Student 14"), rubric on the side, mark (0–points) and feedback, then next. Progress "23 / 60 marked". Toggle to show names |
| Results | Table: student, score, %, pass/fail, grading status, integrity outcome, released. Release button (disabled with the reason if grading is incomplete). Attempt detail page: every answer with score; coding submissions with source, all test case details, and the score calculation |
| Analytics (S) | Score histogram and summary stats; per-question table (avg score, % correct, option-pick counts); coding: verdict counts and pass rate per test case, with low pass rates highlighted ("possibly broken test case") |

### 5.5 Teacher — proctoring review

| Page | Contents |
|---|---|
| Review list | One row per attempt: student, event counts by severity, reviewed / total, integrity outcome. Sort by most HIGH events first. Filter: unreviewed only |
| Attempt timeline | Timeline bar of the attempt with events placed by time (shape and colour by severity). List of events: type, time, duration, severity, confidence. Selecting an event opens the `EvidenceViewer` (images load through 5-min links) and the decision buttons **Dismiss** / **Flag as a concern** with a note field. Connection gaps are shown on the timeline in grey and labelled "connection lost — not an event" |
| Bulk dismiss (S) | Select LOW/MEDIUM events → dismiss with one note. HIGH events can't be selected |
| Detector quality (S) | Per detector: events, dismissed %, flagged % |

The review page always shows this note: "Events are moments detected for review, not findings. Lighting,
camera position and connection problems cause false detections."

### 5.6 Student

| Page | Contents |
|---|---|
| Dashboard | Three sections: **Available now** (with Start / Resume), **Upcoming** (with opening time), **Completed** (with result status) |
| Instructions | Title, teacher, window, duration, number of questions, navigation rule, whether Run Code is available, proctoring mode in plain words, device requirements. Button: "Continue to checks" (proctored) or "Start exam" |
| Pre-check | § 8.1 |
| Results | List of released results; detail page: total, per-question score, coding verdicts and passed counts, teacher feedback, integrity outcome. No correct answers, no hidden test content, no proctoring events |

---

## 6. The exam screen (`/attempt/:attemptId`)

The most important screen. A bug here can cost a student their grade.

### 6.1 Layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Exam title          ⏱ 01:24:37   ✓ All saved   ● Online   ◉ Proctoring on    │
├───────────────┬──────────────────────────────────────────────────────────────┤
│ QUESTIONS     │  Question 7 of 24                [Mark for review]  4 points │
│ ① ② ③ ④ ⑤     │                                                              │
│ ⑥ ⑦ ⑧ ⑨ ⑩     │  <question>                                                  │
│               │                                                              │
│ ■ Answered    │  <answer>                                                    │
│ □ Not answered│                                                              │
│ ◆ Marked      │  [← Previous]               [Clear answer]       [Next →]    │
│ ○ Not visited │                                                              │
│ [Review &     │                                                              │
│  submit]      │                                       ┌─────────┐            │
│               │                                       │self-view│            │
└───────────────┴───────────────────────────────────────┴─────────┴────────────┘
```

The four header indicators (timer, save, connection, proctoring) are always visible and always have text,
not just icons.

### 6.2 Starting and resuming

- Start comes from the instructions/pre-check page; the attempt response contains all questions, so the
  exam works without further page loads.
- On reload or return: answers, drafts, flags and order come from the server, then the local outbox is
  sent. Banner: "Your answers were restored. The timer kept running."
- Fullscreen is requested at start for proctored exams; leaving it is a `TAB_SWITCH` event and a banner
  asks the student to return.

### 6.3 Header indicators

| Indicator | Behaviour |
|---|---|
| Timer | From server time (§ 2.3). Warning style at 10 min, danger style + banner at 2 min. Screen readers hear it at 30, 15, 10, 5, 2 and 1 minutes left, not every second |
| Save status | `All saved` · `Saving…` · `Offline — N answers saved on this device` · `N answers not saved` (danger, after 60 s of failures). While anything is unsent, closing the tab asks for confirmation |
| Connection | `Online` · `Reconnecting…` · `Offline` |
| Proctoring | `Proctoring on` with camera (or camera + mic) icon, and a small self-view the student can shrink but not turn off. If the camera is lost: `Camera not detected — check your camera` |
| Teacher actions | A time extension shows a banner: "Your teacher added 10 minutes" |

### 6.4 Question navigator

| State | Shape |
|---|---|
| Not visited | Outlined circle |
| Not answered | Outlined square |
| Answered | Filled square |
| Marked for review | Outlined diamond |
| Answered & marked | Filled diamond |

- Coding questions show a small "submitted" tick once a submission exists ("wrote code" ≠ "submitted").
- Screen reader name, e.g. "Question 7, answered, marked for review". Arrow keys move, Enter opens.
- Sequential mode: earlier questions are disabled, with a note at the top explaining forward-only.

### 6.5 Answer controls

| Type | Control |
|---|---|
| MCQ / True-False | Radio buttons; saved immediately; **Clear answer** always available |
| MSQ | Checkboxes; the scoring rule is shown in one sentence above the options |
| Descriptive | Text area with live character count; typing stops at the limit |
| Coding | § 7 |

### 6.6 Review and submit

**Review & submit** opens a full page: table of all questions with state, and counts of unanswered, marked,
and coding questions without a submission (each clickable). Confirming shows the counts again; if anything
is unsent, it says how many and asks again. After submitting: a **receipt** (time, automatic or manual,
answered counts, coding evaluations still running) and "Results will appear when your teacher releases
them."

### 6.7 Time up

At 0: inputs lock, the outbox flushes, and a modal says "Time is up. Your exam was submitted
automatically," showing what was saved. If some answers didn't reach the server in time, it says how many,
honestly. Unsubmitted code drafts are graded automatically (PRD EXE-06) and the modal says so.

### 6.8 Rules inside the exam screen

1. **A network error never blocks the student.** Work continues; answers queue on the device.
2. **Session expiry never leaves the page.** Re-login happens in a modal on top of the exam.
3. **Run/Submit progress never covers the question or editor.**
4. **No toasts.** Anything worth saying stays on screen.

---

## 7. Coding question (student)

### 7.1 Layout

```
┌────────────────────────────────┬─────────────────────────────────────────────┐
│ PROBLEM                        │ Language [Python 3.12 ▾]  [Reset to starter]│
│ Statement                      │ ┌─────────────────────────────────────────┐ │
│ Input / Output format          │ │ 1  def main():                          │ │
│ Constraints                    │ │ 2      ...                              │ │
│ Examples                       │ └─────────────────────────────────────────┘ │
│ Limits: 2 s · 256 MB           │ [Run code]  (12 runs left)    [Submit] 3/10 │
│ Counted: best submission       ├─────────────────────────────────────────────┤
│                                │ RESULTS  [Run] [Submissions]                │
│                                │ Test 1 ✓  Test 2 ✗  ...                     │
└────────────────────────────────┴─────────────────────────────────────────────┘
```

Needs at least 1280×720; below that, Problem / Code / Results become tabs with a "use a wider screen" note.

### 7.2 Run vs Submit

They must never be confused:

| | Run code | Submit |
|---|---|---|
| Style | Secondary button | Primary button |
| Tests | Public only | All, including hidden |
| Graded | **No** — "Run results do not affect your score" shown with every result | Yes |
| Limit shown | Runs left; cooldown countdown | Submissions used / allowed |
| Confirmation | None | "Submit for grading? This uses 1 of your 10 submissions." |

Custom input (S): a "Custom input" box next to Run; shows the program's output only.

### 7.3 Language switching

Switching keeps each language's draft separately ("Your Java code is kept"). Reset to starter asks for
confirmation. Drafts autosave like answers.

### 7.4 Results

| Case | Shown |
|---|---|
| Public test case | Input, expected output, your output (differences highlighted, with spaces and line endings made visible), time, memory, result |
| **Hidden test case** | **Only** "Hidden test 4: Passed / Failed". No input, output, timing or error text |
| Compile error | Compiler output in a monospace block; for a submission: "Score 0 — code that doesn't compile scores zero" |
| Submission summary | Verdict, score ("6.25 / 10"), "6 of 8 tests passed" |
| Waiting | "Queued — N ahead" or "Running — 4 s" |
| Platform failure | "We couldn't run this. It's our problem, not yours. Your code is saved and will be re-run. It won't be scored zero." |

### 7.5 Submission history

List: #, time, language, verdict, score, and which one **counts** (best or last), with "View code" for each.

---

## 8. Proctoring UI

### 8.1 Pre-check (`/student/exams/:examId/precheck`)

A `Stepper`; each step must pass (or warn) before the next.

| Step | Contents | Pass condition |
|---|---|---|
| 1. Consent | Consent text (all points from `SECURITY_AND_ACCESS.md` § 8.2). Buttons: **I agree** / **I don't agree**. Declining shows "You can't take this exam without agreeing. Contact your teacher." The camera is not turned on before this step is accepted | Agreed |
| 2. Camera | Browser permission prompt, self-view, "We can see your face" check. Blocked permission → step-by-step help for the browser, and **Re-check** | Face detected |
| 3. Microphone (Video + Audio only) | Level meter: "Say something" | Sound detected |
| 4. Download | Progress bar while models and editor files are downloaded and cached | Done |
| 5. Connection | Measures latency and speed | Always passes; slow → warning "Your connection is slow. Your answers will still be saved." |
| 6. Screen | Window at least 1024×768 (1280×720 for coding) | Passes or warns |
| Ready | Summary and **Start exam** | — |

### 8.2 During the exam

- The header indicator and self-view are the only proctoring UI. **No warnings pop up when something is
  detected**: the student is not told about events (privacy, and to avoid teaching evasion).
- Exception: leaving fullscreen shows "Please return to fullscreen" with a button, because the student
  can fix it.
- Camera lost: header shows the problem and a **Reconnect camera** button; the exam continues.

### 8.3 Teacher review

See § 5.5.

---

## 9. UI states

Named states every page uses.

| State | When | Shown | Recovery |
|---|---|---|---|
| `LOADING` | First load | Skeleton in the final layout | Automatic |
| `ACTION_PENDING` | Button action running | Spinner inside the button | Automatic |
| `EMPTY` | Nothing exists yet | Reason + action to create | Action |
| `EMPTY_FILTERED` | Filters hide everything | "No results for these filters" + **Clear filters** | Clear |
| `ERROR` | Unexpected failure | Plain message + **Retry** | Retry |
| `OFFLINE` | Can't reach server | Outside the exam: banner with auto-retry. In the exam: § 6.8 | Automatic |
| `SESSION_EXPIRED` | Refresh failed | Outside the exam: go to login and come back after. In the exam: login modal on top | Log in |
| `FORBIDDEN` | Wrong role | `/403` with a link home | Navigate |
| `NOT_FOUND` | Missing or not yours | `/404` (same page in both cases) | Navigate |
| `DEVICE_BLOCKED` | Camera/mic permission denied | Browser-specific steps + **Re-check** | Re-check |
| `EXAM_UNAVAILABLE` | Not open yet, closed, or not assigned | Which one, with times; countdown if not open yet | Wait |
| `ALREADY_SUBMITTED` | Opening a finished attempt | The receipt | View |
| `QUEUED_RUNNING` | Code run / submission in progress | Queued with position, or Running with seconds | Automatic |
| `RUN_UNAVAILABLE` | Run Code paused because the server is busy | "Run Code is busy. Submissions still work." | Retry later |

---

## 10. Screen sizes

| Area | Minimum |
|---|---|
| Student dashboard, instructions, results | 360 px (phones fine) |
| Admin and teacher pages | 1024 px (usable read-only at 768 px) |
| Exam screen, no coding | 1024×768 |
| Exam screen, with coding | 1280×720 |
| Proctored exams | Laptop or desktop only — stated on the instructions page and pre-check |

If the window becomes too small during the exam, a banner asks to enlarge it; the exam is never blocked.

---

## 11. Accessibility

| Requirement | How |
|---|---|
| Keyboard | Everything works by keyboard, including the navigator, options, submit and the editor (`Esc` then `Tab` to leave the editor). A "Keyboard shortcuts" help in the exam |
| Screen readers | Labels on all controls; save status and timer use polite live regions (timer only at set intervals); navigator buttons have full state names |
| Not colour alone | Shapes and text for navigator states, test results, severity |
| Contrast | WCAG AA for text and controls |
| Motion | Respects `prefers-reduced-motion` |
| Check | `axe` automated checks in CI on main pages; one manual keyboard-only run-through of a full exam before the demo |
| Known limit | CodeMirror's screen-reader support is good but not perfect; stated on the instructions page for coding exams |
