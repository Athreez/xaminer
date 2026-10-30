"""Proctoring privacy (SECURITY_AND_ACCESS.md § 4.4, § 11; TCK-1401): nothing a student can call
may return proctoring events, their severity or confidence, or evidence. Checked on the API's own
description (OpenAPI), so a route added later can't slip through: every response schema reachable
from a route a student may call is searched for such fields.

The integrity outcome of a released result is allowed (PRD GRD-07): that's the only proctoring
word a student sees.
"""

from typing import Any

from app.authz.guards import access_table
from app.authz.permissions import role_has
from app.core.config import Settings
from app.main import create_app

FORBIDDEN = ("event", "severity", "confidence", "evidence")
ALLOWED = {"integrity_outcome"}


def _fields(schema: Any, components: dict[str, Any], seen: set[str]) -> set[str]:
    """Every property name reachable from this schema."""
    out: set[str] = set()
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str):
            name = ref.rsplit("/", 1)[-1]
            if name not in seen:
                seen.add(name)
                out |= _fields(components.get(name, {}), components, seen)
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                out |= set(value)
                for sub in value.values():
                    out |= _fields(sub, components, seen)
            elif key != "$ref":
                out |= _fields(value, components, seen)
    elif isinstance(schema, list):
        for item in schema:
            out |= _fields(item, components, seen)
    return out


def test_no_student_route_returns_proctoring_details() -> None:
    app = create_app(Settings(environment="test"))
    spec = app.openapi()
    components = spec.get("components", {}).get("schemas", {})
    access = access_table(app)
    leaks = []
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            permission = access.get(f"{method.upper()} {path}")
            if permission is None or not (
                permission == "public" or role_has("STUDENT", permission)
            ):
                continue
            fields = _fields(operation.get("responses", {}), components, set())
            bad = sorted(
                f for f in fields - ALLOWED if any(word in f.lower() for word in FORBIDDEN)
            )
            if bad:
                leaks.append(f"{method.upper()} {path}: {bad}")
    assert not leaks, "student-callable responses with proctoring details:\n" + "\n".join(leaks)


def test_the_check_would_catch_one() -> None:
    components = {"Row": {"properties": {"severity": {"type": "string"}}}}
    found = _fields({"schema": {"$ref": "#/components/schemas/Row"}}, components, set())
    assert "severity" in found
