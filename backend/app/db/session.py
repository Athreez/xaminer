"""Engine and sessions. Import this module (not tenancy directly) so the tenant filter is active."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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
