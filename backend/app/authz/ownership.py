"""Load an item by id and check it belongs to the caller (SECURITY_AND_ACCESS.md § 4.1).

Anything the caller may not see answers 404, exactly like an id that doesn't exist, so a response
never confirms that someone else's exam, attempt or result exists:

    exam = await get_owned(
        db, Exam, exam_id, principal, owned=lambda e: e.owner_id == principal.user_id
    )

The check runs on the *loaded* item, never on the id alone.
"""

import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import Principal
from app.core.errors import AppError
from app.db.base import TenantMixin


def not_found() -> AppError:
    return AppError("NOT_FOUND", "Not found.", status_code=404)


async def get_owned[T: TenantMixin](
    session: AsyncSession,
    model: type[T],
    item_id: uuid.UUID,
    principal: Principal,
    owned: Callable[[T], bool] | None = None,
) -> T:
    """The item, if it exists, is in the caller's institution and passes `owned`; else 404.

    `session` should be the caller's tenant session, which already filters queries by institution.
    The institution is compared again here because `session.get` can return an object from the
    session's memory without running a query, and then the automatic filter never applies.
    """
    item = await session.get(model, item_id)
    if item is None or item.institution_id != principal.institution_id:
        raise not_found()
    if owned is not None and not owned(item):
        raise not_found()
    return item
