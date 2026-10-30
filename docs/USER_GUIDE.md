# Xaminer user guide

How to use Xaminer as an admin, a teacher or a student. To set up and run it, see the README.

## Logging in

Open the address you were given (e.g. `https://192.168.1.20:8443`) and log in with your email and
password. New accounts get an email with a link to set a password; **Forgot password?** on the
login page sends a new one. Five wrong passwords in a row lock the account for 15 minutes.

## Admin

The admin manages people, not exams: you never see questions, answers or code.

| Page | What you do there |
|---|---|
| **Users** | Add one person (they get an invitation email) or **Import CSV** for many. Change a role, deactivate someone, or send a password reset |
| **Groups** | Make groups such as "CSE 2nd year" and add students; teachers assign exams to whole groups |
| **Exams** | See every exam in the college: title, teacher, dates and status |
| **Settings** | How long webcam images are kept (7–90 days) and the consent text for proctored exams. Empty, the standard text is used; **Start from the standard text** lets you edit it |
| **Audit log** | Who did what and when: logins, user changes, publishing, marks, releases |

## Teacher

### 1. Questions

**Questions → New question**. Types: single choice, multiple choice, true/false, written answer
and coding. Write in Markdown (bold, lists, code, images). Points and negative marks are per
question. **Private** questions are yours; **Institution** ones colleagues can use and copy.

**Coding questions** have four tabs: *Problem* (statement, input and output format),
*Languages & limits* (allowed languages with starter code, time and memory limits),
*Test cases* (**public** ones are shown to students as examples, **hidden** ones only grade) and
*Validate* (your reference solution must pass every test case; an exam can't be published
otherwise).

Editing a question that a published exam uses makes a new version; the exam keeps the old one.

### 2. Exams

**Exams → New exam**, then the tabs:

- **Questions:** add from the bank, drag to reorder, change marks for this exam, **Save questions**.
- **Settings:** the window (when it opens and closes), duration, navigation, shuffling, Run Code,
  how results are released (*manually* or *on submit*), pass mark, proctoring.
- **Students:** assign groups or single students.
- **Publish:** shows what still blocks publishing, each with a link to fix it. After publishing,
  only the window's end can change.
- **Overview:** **Try it as a student** opens the real exam screen for you (previews never count).

Extending a student's time, force-submitting or voiding an attempt (each needs a reason) works
through the API for now; the Monitor tab with these buttons comes later.

### 3. Grading and results

Multiple choice, true/false and coding are graded automatically when an attempt ends.

- **Grading:** written answers, one at a time, students shown as "Student 14" (tick **Show names**
  to see them). Type the mark, press Enter: it saves and opens the next answer.
- **Results:** every student's score, percentage, pass/fail and grading status. **Release
  results** stays disabled, with the reason, until everything is graded. Click a name for every
  answer with its score and the correct answer.
- **Re-evaluate code:** after fixing a coding question's test case (and validating it), re-run
  every submission to it. Changed released scores are shown to the student with your reason.
- Changing a mark after release needs a reason; the student sees the old and new score.

The **Dashboard** lists what needs you: answers to mark and results to release.

## Student

### Taking an exam

1. **Dashboard:** exams *available now* (Start or Resume), *upcoming* (when they open) and
   *completed*.
2. **Start** shows the instructions and the time allowed. The timer starts when you start, and
   never runs past the window's end.
3. Answer in any order (unless the exam says otherwise). Every answer saves itself; the header
   shows **Saved** or how many are waiting. If the internet drops, keep going: answers are kept
   on your device and sent when it's back. Don't clear the browser's data during an exam.
4. **Mark for review** flags a question for later. **Review & submit** lists what's unanswered.
5. When time is up the exam submits itself. You get a **receipt code** either way.

### Coding questions

Write code in one of the allowed languages (each keeps its own draft). **Run** tests your code on
the public examples or on your own input; it is never graded. **Submit** grades it on every test
case: hidden tests show only passed or failed. Submissions are limited per question; your best
one counts (unless the teacher chose the last). When the exam ends, your latest unsubmitted code
is submitted for you.

### Results

**Results** lists your exams. A score appears once your teacher releases it (or right away for
exams released on submit): your total, each question's score, feedback on written answers and how
your code did. Correct answers are not shown.

## Proctored exams

Some exams use your webcam. Before starting you read and accept the consent text: what is used,
that checks run on your own device and nothing is recorded, when a still image is kept, who can
see it, for how long, and what happens if you decline (you can't take that exam; talk to your
teacher). A teacher reviews everything; nothing is decided automatically.
