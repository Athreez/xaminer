"""Automatic institution (tenant) filtering for every ORM query (PRD ACC-02).

A session is opened either for one institution (`tenant_session`) or, rarely, as a system session
(`system_session`) for CLI commands and cross-institution background jobs. Then:

- every ORM SELECT / UPDATE / DELETE on a TenantMixin table is limited to the session's institution;
- new TenantMixin rows get the session's institution_id, and a different one is refused;
- an ORM query in a session that is neither raises TenantScopeError: forgetting is an error,
  not a data leak.

Raw SQL (`text(...)`) is NOT filtered; repository code that uses it must filter by hand.
"""

import uuid
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.db.base import TenantMixin

TENANT_KEY = "institution_id"
SYSTEM_KEY = "system_session"


class TenantScopeError(RuntimeError):
    """A query ran without an institution scope, or tried to write another institution's row."""


def session_institution(session: Session) -> uuid.UUID | None:
    value = session.info.get(TENANT_KEY)
    return value if isinstance(value, uuid.UUID) else None


@event.listens_for(Session, "do_orm_execute")
def _filter_by_institution(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if state.session.info.get(SYSTEM_KEY):
        return
    institution_id = session_institution(state.session)
    if institution_id is None:
        raise TenantScopeError(
            "Query without an institution scope. Use tenant_session() (or system_session() "
            "for system jobs)."
        )
    state.statement = state.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda cls: cls.institution_id == institution_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _stamp_institution(session: Session, _context: Any, _instances: Any) -> None:
    institution_id = session_institution(session)
    for obj in session.new:
        if not isinstance(obj, TenantMixin):
            continue
        if institution_id is None:
            if not session.info.get(SYSTEM_KEY):
                raise TenantScopeError("Insert without an institution scope.")
            if obj.institution_id is None:
                raise TenantScopeError("System sessions must set institution_id explicitly.")
        elif obj.institution_id is None:
            obj.institution_id = institution_id
        elif obj.institution_id != institution_id:
            raise TenantScopeError("Refusing to write a row for another institution.")
