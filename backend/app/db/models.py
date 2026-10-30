"""Imports every module's models so `Base.metadata` is complete (Alembic, and workers that load
only some modules: foreign keys need every table they point at)."""

from app.attempts.models import Answer, AttemptQuestion, CodeDraft, ExamAttempt
from app.audit.models import AuditLog
from app.auth.models import AuthToken, RefreshToken
from app.db.base import Base
from app.exams.models import Exam, ExamAssignment, ExamQuestion, ExamVersion
from app.execution.models import CodeRun, CodingEvaluation, CodingSubmission, TestCaseResult
from app.notifications.models import Notification
from app.platform.models import Institution, Language
from app.proctoring.models import ProctoringEvent
from app.questions.models import (
    CodingConfig,
    Question,
    QuestionOption,
    QuestionVersion,
    ReferenceSolution,
    TestCase,
)
from app.results.models import Result, ResultRevision
from app.users.models import User, UserGroup, UserGroupMember

__all__ = [
    "Answer",
    "AttemptQuestion",
    "AuditLog",
    "AuthToken",
    "Base",
    "CodeDraft",
    "CodeRun",
    "CodingConfig",
    "CodingEvaluation",
    "CodingSubmission",
    "Exam",
    "ExamAssignment",
    "ExamAttempt",
    "ExamQuestion",
    "ExamVersion",
    "Institution",
    "Language",
    "Notification",
    "ProctoringEvent",
    "Question",
    "QuestionOption",
    "QuestionVersion",
    "ReferenceSolution",
    "RefreshToken",
    "Result",
    "ResultRevision",
    "TestCase",
    "TestCaseResult",
    "User",
    "UserGroup",
    "UserGroupMember",
]
