"""Route guards. Every API route must declare one (SECURITY_AND_ACCESS.md § 3.1):

    @router.get("/users", dependencies=[Depends(require(P.USER_READ))])   # role must have it
    @router.post("/login", dependencies=[PUBLIC])                         # open to everyone

`assert_routes_declared` runs when the app is created and refuses to start if any route has
neither, so a forgotten check fails immediately instead of shipping an open endpoint.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts

from app.auth.dependencies import get_principal
from app.auth.tokens import Principal
from app.authz.permissions import Permission, role_has
from app.core.errors import AppError

_PERMISSION_ATTR = "__xaminer_permission__"
_PUBLIC_ATTR = "__xaminer_public__"


def require(permission: Permission) -> Callable[..., Awaitable[Principal]]:
    """A dependency that lets the request through only if the caller's role has `permission`.

    It returns the caller, so a route can take it as a parameter instead of `dependencies=[...]`.
    """

    async def check(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if not role_has(principal.role, permission):
            raise AppError("FORBIDDEN", "You don't have permission to do this.", status_code=403)
        return principal

    setattr(check, _PERMISSION_ATTR, permission)
    check.__name__ = f"require_{permission.value.replace(':', '_').replace('-', '_')}"
    return check


async def _public() -> None:
    """Marks a route as deliberately open to everyone (login, health, password reset...)."""


setattr(_public, _PUBLIC_ATTR, True)
PUBLIC: Any = Depends(_public)


def route_access(dependant: Dependant) -> str | None:
    """The permission a route declares, 'public', or None if it declares nothing."""
    for dependency in dependant.dependencies:
        if getattr(dependency.call, _PUBLIC_ATTR, False):
            return "public"
        permission = getattr(dependency.call, _PERMISSION_ATTR, None)
        if permission is not None:
            return str(permission)
        nested = route_access(dependency)
        if nested is not None:
            return nested
    return None


def access_table(app: FastAPI) -> dict[str, str | None]:
    """'METHOD /path' -> declared access, for every API route (used by tests and the check).

    FastAPI 0.162+ keeps included routers nested, so `app.routes` alone doesn't list them; its
    public `iter_route_contexts` walks into them and gives each route its full path and its
    effective dependencies (including any set on the router).
    """
    table: dict[str, str | None] = {}
    for context in iter_route_contexts(app.routes):
        if not isinstance(context.original_route, APIRoute):
            continue  # FastAPI's own docs and OpenAPI routes
        dependant: Dependant = context.dependant
        for method in sorted(context.methods or ()):
            table[f"{method} {context.path}"] = route_access(dependant)
    if not table:
        raise RuntimeError("No API routes found: the permission check would be checking nothing.")
    return table


def assert_routes_declared(app: FastAPI) -> None:
    missing = [route for route, access in access_table(app).items() if access is None]
    if missing:
        raise RuntimeError(
            "These routes declare no permission. Add dependencies=[Depends(require(...))] "
            "or dependencies=[PUBLIC]: " + ", ".join(missing)
        )
