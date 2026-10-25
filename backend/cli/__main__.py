"""platform-admin: set-up commands for the people running the platform (not a user role).

    python -m cli create-institution --name "ABC College" [--timezone Asia/Kolkata]
    python -m cli list-institutions
    python -m cli list-languages

In Docker:  docker compose -f deploy/docker-compose.yml run --rm api python -m cli <command>
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable

from app.core.config import get_settings
from app.db.session import SessionFactory, create_engine, create_session_factory
from cli import commands


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="platform-admin", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-institution", help="Create a new institution (tenant).")
    create.add_argument("--name", required=True)
    create.add_argument("--timezone", default=commands.DEFAULT_TIMEZONE)

    sub.add_parser("list-institutions", help="List all institutions.")
    sub.add_parser("list-languages", help="List the programming language catalogue.")
    return parser


async def _run(args: argparse.Namespace) -> None:
    engine = create_engine(get_settings().database_url("app"))
    factory = create_session_factory(engine)
    handlers: dict[str, Callable[[SessionFactory, argparse.Namespace], Awaitable[None]]] = {
        "create-institution": _create_institution,
        "list-institutions": _list_institutions,
        "list-languages": _list_languages,
    }
    try:
        await handlers[args.command](factory, args)
    finally:
        await engine.dispose()


async def _create_institution(factory: SessionFactory, args: argparse.Namespace) -> None:
    institution = await commands.create_institution(factory, args.name, args.timezone)
    print(f"Created institution {institution.name!r}")
    print(f"  id:       {institution.id}")
    print(f"  timezone: {institution.timezone}")


async def _list_institutions(factory: SessionFactory, _: argparse.Namespace) -> None:
    rows = await commands.list_institutions(factory)
    if not rows:
        print("No institutions yet. Create one with: create-institution --name ...")
    for row in rows:
        print(f"{row.id}  {row.status:<9}  {row.timezone:<16}  {row.name}")


async def _list_languages(factory: SessionFactory, _: argparse.Namespace) -> None:
    for lang in await commands.list_languages(factory):
        state = "enabled" if lang.enabled else "disabled"
        print(f"{lang.key:<10}  {state:<8}  x{lang.time_multiplier}  {lang.display_name}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        asyncio.run(_run(args))
    except commands.CommandError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
