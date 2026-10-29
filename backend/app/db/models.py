"""Imports every module's models so `Base.metadata` is complete (used by Alembic)."""

from app.attempts.models import Answer, AttemptQuestion, CodeDraft, ExamAttempt
from app.audit.models import AuditLog
from app.auth.models import AuthToken, RefreshToken
from app.db.base import Base
from app.exams.models import Exam, ExamAssignment, ExamQuestion, ExamVersion
from app.platform.models import Institution, Language
from app.questions.models import Question, QuestionOption, QuestionVersion
from app.users.models import User, UserGroup, UserGroupMember

__all__ = [
    "Answer",
    "AttemptQuestion",
    "AuditLog",
    "AuthToken",
    "Base",
    "CodeDraft",
    "Exam",
    "ExamAssignment",
    "ExamAttempt",
    "ExamQuestion",
    "ExamVersion",
    "Institution",
    "Language",
    "Question",
    "QuestionOption",
    "QuestionVersion",
    "RefreshToken",
    "User",
    "UserGroup",
    "UserGroupMember",
]
