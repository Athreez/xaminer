"""platform-admin: set-up commands for the people running the platform (not a user role).

    python -m cli create-institution --name "ABC College" [--timezone Asia/Kolkata]
    python -m cli create-admin --institution "ABC College" --email a@abc.edu --name "Asha Rao"
    python -m cli invite-user --institution "ABC" --email s@abc.edu --name "Ravi K" --role STUDENT
    python -m cli list-institutions
    python -m cli list-languages

In Docker:  docker compose -f deploy/docker-compose.yml run --rm api python -m cli <command>
"""

import argparse
import asyncio
import getpass
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

    admin = sub.add_parser(
        "create-admin",
        help="Create the first admin of an institution. Asks for the password (hidden).",
    )
    admin.add_argument("--institution", required=True, help="Institution id or exact name")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True, help="Full name")
    admin.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from standard input instead of prompting (for scripts)",
    )

    invite = sub.add_parser(
        "invite-user",
        help="Create a user and email them an activation link (re-sends if still invited).",
    )
    invite.add_argument("--institution", required=True, help="Institution id or exact name")
    invite.add_argument("--email", required=True)
    invite.add_argument("--name", required=True, help="Full name")
    invite.add_argument("--role", required=True, choices=["ADMIN", "TEACHER", "STUDENT"])
    invite.add_argument("--roll-no", default=None, help="Optional student roll number")

    sub.add_parser("list-institutions", help="List all institutions.")
    sub.add_parser("list-languages", help="List the programming language catalogue.")
    return parser


async def _run(args: argparse.Namespace) -> None:
    engine = create_engine(get_settings().database_url("app"))
    factory = create_session_factory(engine)
    handlers: dict[str, Callable[[SessionFactory, argparse.Namespace], Awaitable[None]]] = {
        "create-institution": _create_institution,
        "create-admin": _create_admin,
        "invite-user": _invite_user,
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


def _read_password(from_stdin: bool) -> str:
    """Never take a password as an argument: it would end up in shell history."""
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    try:
        first = getpass.getpass("Password (hidden): ")
        if getpass.getpass("Repeat password: ") != first:
            raise commands.CommandError("Passwords don't match.")
    except EOFError as exc:
        raise commands.CommandError(
            "No password entered. Run this in an interactive terminal, or use --password-stdin."
        ) from exc
    return first


async def _create_admin(factory: SessionFactory, args: argparse.Namespace) -> None:
    admin = await commands.create_admin(
        factory, args.institution, args.email, args.name, args.password
    )
    print(f"Created admin {admin.full_name} <{admin.email}>  (id {admin.id})")
    print("They can log in once the login page exists (TCK-0110).")


async def _invite_user(factory: SessionFactory, args: argparse.Namespace) -> None:
    user, created = await commands.invite_user(
        factory,
        args.institution,
        args.email,
        args.name,
        args.role,
        get_settings().public_base_url,
        roll_no=args.roll_no,
    )
    action = "Invited" if created else "Re-sent the invitation to"
    print(f"{action} {user.full_name} <{user.email}> as {user.role}.")
    print("The email is on its way (in development: http://localhost:8025).")


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
        if args.command == "create-admin":
            # Asked before connecting, so a typo doesn't leave a half-open database connection.
            args.password = _read_password(args.password_stdin)
        asyncio.run(_run(args))
    except commands.CommandError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
