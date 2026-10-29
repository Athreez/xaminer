"""The automatic institution filter (PRD ACC-02, architecture § 5 'Tenant scoping')."""

import uuid

import pytest
from sqlalchemy import String, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin
from app.db.session import SessionFactory, create_session_factory, system_session, tenant_session
from app.db.tenancy import TenantScopeError
from app.platform.models import Institution


class Note(IdMixin, TenantMixin, Base):
    """Test-only tenant table."""

    __tablename__ = "test_tenant_note"
    body: Mapped[str] = mapped_column(String(50))


@pytest.fixture
async def factory(migrator_engine: AsyncEngine, app_engine: AsyncEngine) -> SessionFactory:
    # Made once and kept for the run (dropping it would lock `institution` for every worker);
    # the next run's schema reset removes it (conftest.TEST_TABLES).
    async with migrator_engine.begin() as conn:
        await conn.run_sync(lambda c: Note.__table__.create(c, checkfirst=True))
    return create_session_factory(app_engine)


@pytest.fixture
async def two_institutions(factory: SessionFactory) -> tuple[uuid.UUID, uuid.UUID]:
    a, b = Institution(name="College A"), Institution(name="College B")
    async with system_session(factory) as s:
        s.add_all([a, b])
        await s.flush()
        s.add_all(
            [
                Note(institution_id=a.id, body="a1"),
                Note(institution_id=a.id, body="a2"),
                Note(institution_id=b.id, body="b1"),
            ]
        )
        await s.commit()
    return a.id, b.id


async def test_select_sees_only_own_institution(
    factory: SessionFactory, two_institutions: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_institutions
    async with tenant_session(factory, a) as s:
        bodies = sorted((await s.scalars(select(Note.body))).all())
    assert bodies == ["a1", "a2"]
    async with tenant_session(factory, b) as s:
        assert (await s.scalar(select(func.count()).select_from(Note))) == 1


async def test_get_by_id_of_other_institution_returns_nothing(
    factory: SessionFactory, two_institutions: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_institutions
    async with tenant_session(factory, b) as s:
        b_note_id = (await s.scalars(select(Note.id))).one()
    async with tenant_session(factory, a) as s:
        found = (await s.scalars(select(Note).where(Note.id == b_note_id))).first()
    assert found is None


async def test_update_and_delete_are_scoped(
    factory: SessionFactory, two_institutions: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_institutions
    async with tenant_session(factory, a) as s:
        await s.execute(update(Note).values(body="changed"))
        await s.execute(delete(Note).where(Note.body == "b1"))
        await s.commit()
    async with tenant_session(factory, b) as s:
        assert (await s.scalars(select(Note.body))).all() == ["b1"]


async def test_insert_gets_session_institution(
    factory: SessionFactory, two_institutions: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_institutions
    async with tenant_session(factory, a) as s:
        note = Note(body="new")
        s.add(note)
        await s.commit()
    assert note.institution_id == a


async def test_insert_for_other_institution_refused(
    factory: SessionFactory, two_institutions: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_institutions
    async with tenant_session(factory, a) as s:
        s.add(Note(institution_id=b, body="smuggled"))
        with pytest.raises(TenantScopeError):
            await s.flush()


async def test_query_without_scope_is_an_error(factory: SessionFactory) -> None:
    async with factory() as s:
        with pytest.raises(TenantScopeError):
            await s.execute(select(Note))
