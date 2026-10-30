"""Permission names and the role table (SECURITY_AND_ACCESS.md § 3.2).

The table lives in code, not in the database: there are no custom roles, and a permission table
that can be edited at runtime would be a way to grant yourself more access.

A permission says what a role may do at all. Whether a user may do it to *this* item (their own
exam, their own attempt) is a separate ownership check on the loaded item (TCK-0108).
"""

from enum import StrEnum


class Permission(StrEnum):
    # Own account: /auth/me, log out everywhere, change own password, own notifications.
    ACCOUNT_SELF = "account:self"
    NOTIFICATION_READ = "notification:read"

    # Users and setup
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    GROUP_READ = "group:read"
    GROUP_WRITE = "group:write"
    INSTITUTION_SETTINGS_WRITE = "institution-settings:write"
    AUDIT_LOG_READ = "audit-log:read"

    # Questions
    QUESTION_READ = "question:read"
    QUESTION_WRITE = "question:write"
    QUESTION_COPY = "question:copy"
    TEST_CASE_READ_HIDDEN = "test-case:read-hidden"
    TEST_CASE_WRITE = "test-case:write"
    REFERENCE_SOLUTION_WRITE = "reference-solution:write"
    QUESTION_VALIDATE = "question:validate"

    # Exams and attempts
    EXAM_READ = "exam:read"
    EXAM_LIST_ALL = "exam:list-all"  # every exam of the institution, metadata only (admins)
    EXAM_WRITE = "exam:write"
    ATTEMPT_TAKE = "attempt:take"
    ATTEMPT_READ = "attempt:read"
    ATTEMPT_MANAGE = "attempt:manage"
    SUBMISSION_READ_FULL = "submission:read-full"
    SUBMISSION_READ_STUDENT_VIEW = "submission:read-student-view"
    SUBMISSION_RE_EVALUATE = "submission:re-evaluate"

    # Grading and results
    GRADING_WRITE = "grading:write"
    RESULT_READ = "result:read"
    RESULT_RELEASE = "result:release"
    ANALYTICS_READ = "analytics:read"
    MONITOR_READ = "monitor:read"

    # Proctoring
    PROCTORING_UPLOAD = "proctoring:upload"
    PROCTORING_EVENT_READ = "proctoring-event:read"
    EVIDENCE_READ = "evidence:read"
    PROCTORING_EVENT_REVIEW = "proctoring-event:review"
    CONSENT_READ = "consent:read"
    INTEGRITY_OUTCOME_READ = "integrity-outcome:read"


P = Permission

_EVERYONE = {P.ACCOUNT_SELF, P.NOTIFICATION_READ}

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    # Manages accounts, not exams: never sees questions, answers, code or evidence (§ 3.2).
    "ADMIN": frozenset(
        _EVERYONE
        | {
            P.USER_READ,
            P.USER_WRITE,
            P.GROUP_READ,
            P.GROUP_WRITE,
            P.INSTITUTION_SETTINGS_WRITE,
            P.AUDIT_LOG_READ,
            P.EXAM_READ,  # title, dates and status only
            P.EXAM_LIST_ALL,
        }
    ),
    "TEACHER": frozenset(
        _EVERYONE
        | {
            P.USER_READ,  # self + students assigned to own exams
            P.GROUP_READ,
            P.QUESTION_READ,
            P.QUESTION_WRITE,
            P.QUESTION_COPY,
            P.TEST_CASE_READ_HIDDEN,
            P.TEST_CASE_WRITE,
            P.REFERENCE_SOLUTION_WRITE,
            P.QUESTION_VALIDATE,
            P.EXAM_READ,
            P.EXAM_WRITE,
            P.ATTEMPT_TAKE,  # own preview attempts
            P.ATTEMPT_READ,
            P.ATTEMPT_MANAGE,
            P.SUBMISSION_READ_FULL,
            P.SUBMISSION_RE_EVALUATE,
            P.GRADING_WRITE,
            P.RESULT_READ,
            P.RESULT_RELEASE,
            P.ANALYTICS_READ,
            P.MONITOR_READ,
            P.PROCTORING_UPLOAD,  # own preview attempts
            P.PROCTORING_EVENT_READ,
            P.EVIDENCE_READ,
            P.PROCTORING_EVENT_REVIEW,
            P.CONSENT_READ,
            P.INTEGRITY_OUTCOME_READ,
        }
    ),
    # Sees only their own work, and never hidden tests, full submissions or proctoring events.
    "STUDENT": frozenset(
        _EVERYONE
        | {
            P.USER_READ,  # self only
            P.EXAM_READ,  # assigned exams, student view
            P.ATTEMPT_TAKE,
            P.ATTEMPT_READ,
            P.SUBMISSION_READ_STUDENT_VIEW,
            P.RESULT_READ,  # released only
            P.PROCTORING_UPLOAD,  # attempt token only
            P.CONSENT_READ,
            P.INTEGRITY_OUTCOME_READ,  # on a released result
        }
    ),
}


def role_has(role: str, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
