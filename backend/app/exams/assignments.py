"""Who may take an exam (PRD EX-04). No assignment, no attempt.

Teachers assign whole groups and/or single students. A group becomes one row per student at that
moment (students added to the group later are not included automatically). Deactivated students
are skipped; students already assigned are left as they are. Assignments can change while the
exam is a draft or published, not once archived.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import not_found
from app.core.errors import AppError
from app.core.pagination import like_pattern
from app.exams.models import Exam, ExamAssignment
from app.exams.service import get_own
from app.users.models import User, UserGroup, UserGroupMember
from app.users.schemas import StatusName


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_ids: list[uuid.UUID] = Field(default=[], max_length=50)
    student_ids: list[uuid.UUID] = Field(default=[], max_length=2_000)


class AssignResult(BaseModel):
    added: int = Field(description="Students newly assigned")
    already_assigned: int
    skipped_inactive: int = Field(description="Deactivated students in the groups, not assigned")


class AssignedStudent(BaseModel):
    student_id: uuid.UUID
    full_name: str
    email: str
    roll_no: str | None
    status: StatusName
    via_group: str | None = Field(description="The group it came from, if any")
    assigned_at: datetime


class Assignments(BaseModel):
    students: list[AssignedStudent] = Field(description="By roll number, then name")


class StudentChoice(BaseModel):
    """Just enough to pick a student (SECURITY_AND_ACCESS.md § 3)."""

    id: uuid.UUID
    full_name: str
    email: str
    roll_no: str | None
    assigned: bool


def _invalid(
    field: str, message: str, status: int = 422, code: str = "VALIDATION_FAILED"
) -> AppError:
    return AppError(
        code,
        message,
        status_code=status,
        details=[{"field": field, "message": message, "type": "exam"}],
    )


def _check_open(exam: Exam) -> None:
    if exam.status == "ARCHIVED":
        raise _invalid(
            "status", "This exam is archived and can't be changed.", 409, "EXAM_ARCHIVED"
        )


def _eligible() -> Any:
    return (User.role == "STUDENT") & (User.status != "DEACTIVATED")


async def list_assignments(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID
) -> Assignments:
    exam = await get_own(session, principal, exam_id)
    rows = (
        await session.execute(
            select(ExamAssignment, User, UserGroup.name)
            .join(User, User.id == ExamAssignment.student_id)
            .outerjoin(UserGroup, UserGroup.id == ExamAssignment.via_group_id)
            .where(ExamAssignment.exam_id == exam.id)
            .order_by(User.roll_no.asc().nulls_last(), User.full_name)
        )
    ).all()
    return Assignments(
        students=[
            AssignedStudent(
                student_id=u.id,
                full_name=u.full_name,
                email=u.email,
                roll_no=u.roll_no,
                status=u.status,  # type: ignore[arg-type]
                via_group=group,
                assigned_at=a.created_at,
            )
            for a, u, group in rows
        ]
    )


async def assign(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID, body: AssignRequest
) -> AssignResult:
    exam = await get_own(session, principal, exam_id)
    _check_open(exam)
    group_ids = list(dict.fromkeys(body.group_ids))
    student_ids = list(dict.fromkeys(body.student_ids))
    if not group_ids and not student_ids:
        raise _invalid("student_ids", "Choose at least one group or student.")

    found_groups = set(
        await session.scalars(select(UserGroup.id).where(UserGroup.id.in_(group_ids)))
    )
    for i, gid in enumerate(group_ids):
        if gid not in found_groups:
            raise _invalid(f"group_ids.{i}", "This group doesn't exist.")
    eligible_singles = set(
        await session.scalars(select(User.id).where(User.id.in_(student_ids), _eligible()))
    )
    for i, sid in enumerate(student_ids):
        if sid not in eligible_singles:
            raise _invalid(
                f"student_ids.{i}",
                "Only active or invited students of your institution can be assigned.",
            )

    # (student, group it came through). Single picks win over groups for the record.
    wanted: dict[uuid.UUID, uuid.UUID | None] = {}
    skipped = 0
    if group_ids:
        members = (
            await session.execute(
                select(UserGroupMember.user_id, UserGroupMember.group_id, User.status)
                .join(User, User.id == UserGroupMember.user_id)
                .where(UserGroupMember.group_id.in_(group_ids), User.role == "STUDENT")
            )
        ).all()
        for uid, gid, user_status in members:
            if user_status == "DEACTIVATED":
                skipped += 1
            else:
                wanted.setdefault(uid, gid)
    for sid in student_ids:
        wanted[sid] = None

    already = set(
        await session.scalars(
            select(ExamAssignment.student_id).where(
                ExamAssignment.exam_id == exam.id, ExamAssignment.student_id.in_(wanted)
            )
        )
    )
    new = {uid: gid for uid, gid in wanted.items() if uid not in already}
    if new:
        # ON CONFLICT DO NOTHING: two teachers' tabs assigning at once never fail or double up.
        await session.execute(
            insert(ExamAssignment)
            .values(
                [
                    {
                        "institution_id": principal.institution_id,
                        "exam_id": exam.id,
                        "student_id": uid,
                        "assigned_by": principal.user_id,
                        "via_group_id": gid,
                    }
                    for uid, gid in new.items()
                ]
            )
            .on_conflict_do_nothing(index_elements=["exam_id", "student_id"])
        )
        record(
            session,
            "exam.students_assigned",
            institution_id=principal.institution_id,
            actor_id=principal.user_id,
            actor_role=principal.role,
            target_type="exam",
            target_id=exam.id,
            changes={"added": len(new), "group_ids": [str(g) for g in group_ids]},
        )
        await session.commit()
    return AssignResult(added=len(new), already_assigned=len(already), skipped_inactive=skipped)


async def unassign(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID, student_id: uuid.UUID
) -> None:
    exam = await get_own(session, principal, exam_id)
    _check_open(exam)
    # Once attempts exist (E06), a student who has started can't be removed; voiding is the way.
    removed = await session.execute(
        delete(ExamAssignment).where(
            ExamAssignment.exam_id == exam.id, ExamAssignment.student_id == student_id
        )
    )
    if not removed.rowcount:  # type: ignore[attr-defined]
        raise not_found()
    record(
        session,
        "exam.student_unassigned",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="exam",
        target_id=exam.id,
        changes={"student_id": str(student_id)},
    )
    await session.commit()


async def search_students(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID, q: str | None, limit: int
) -> list[StudentChoice]:
    """Students who could be assigned, for the picker: name, email and roll number only."""
    exam = await get_own(session, principal, exam_id)
    assigned = (
        select(func.count())
        .where(ExamAssignment.exam_id == exam.id, ExamAssignment.student_id == User.id)
        .scalar_subquery()
    )
    query = (
        select(User, assigned)
        .where(_eligible())
        .order_by(User.roll_no.asc().nulls_last(), User.full_name)
        .limit(limit)
    )
    if q and q.strip():
        pattern = like_pattern(q.strip())
        query = query.where(
            User.full_name.ilike(pattern, escape="\\")
            | User.email.ilike(pattern, escape="\\")
            | User.roll_no.ilike(pattern, escape="\\")
        )
    return [
        StudentChoice(
            id=u.id, full_name=u.full_name, email=u.email, roll_no=u.roll_no, assigned=bool(n)
        )
        for u, n in (await session.execute(query)).all()
    ]
