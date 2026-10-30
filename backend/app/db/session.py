"""Engine and sessions. Import this module (not tenancy directly) so the tenant filter is active."""

import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from sqlalchemy import URL, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from app.db import tenancy

SessionFactory = async_sessionmaker[AsyncSession]


def create_engine(url: URL) -> AsyncEngine:
    # Small, bounded pool: many API processes share one Postgres (architecture § 11).
    return create_async_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def tenant_session(
    factory: SessionFactory, institution_id: uuid.UUID
) -> AsyncIterator[AsyncSession]:
    """A session that can only see and write rows of one institution."""
    async with factory() as session:
        session.info[tenancy.TENANT_KEY] = institution_id
        yield session


@asynccontextmanager
async def system_session(factory: SessionFactory) -> AsyncIterator[AsyncSession]:
    """Unfiltered session for CLI commands and cross-institution jobs. Use sparingly."""
    async with factory() as session:
        session.info[tenancy.SYSTEM_KEY] = True
        yield session


# ----------------------------------------------------------------------------- after commit

_AFTER_COMMIT = "after_commit"
logger = logging.getLogger(__name__)


def after_commit(session: AsyncSession, action: Callable[[], None]) -> None:
    """Run `action` once this session's transaction commits (dropped if it rolls back). For work
    that must only start once the change is visible, e.g. a background job about it."""
    session.sync_session.info.setdefault(_AFTER_COMMIT, []).append(action)


@event.listens_for(Session, "after_commit")
def _run_after_commit(session: Session) -> None:
    for action in session.info.pop(_AFTER_COMMIT, []):
        try:
            action()
        except Exception:  # the commit already happened; never undo it over a follow-up
            logger.exception("after-commit action failed")


@event.listens_for(Session, "after_rollback")
def _drop_after_commit(session: Session) -> None:
    session.info.pop(_AFTER_COMMIT, None)
