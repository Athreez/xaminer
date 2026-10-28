"""CSV import of users (PRD USR-03). Limits from SECURITY_AND_ACCESS.md: 1 MB, 2,000 rows.

The page reads the file and sends its text; the same call previews (`dry_run`) or imports, so
nothing is stored between the two steps. Rows with errors are reported and left out; emails that
already have an account are skipped; every other row becomes an INVITED user with an invitation.
"""

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import diff, record
from app.auth.models import AuthToken
from app.auth.tokens import Principal, new_opaque_token
from app.core.errors import AppError
from app.notifications.emails import INVITE_DAYS, Email, invitation_email, queue_email
from app.platform.models import Institution
from app.users.models import ROLES, User

MAX_CHARS = 1_000_000
BOM = chr(0xFEFF)
MAX_ROWS = 2_000

# Header spellings people actually use, mapped to our field names.
HEADERS = {
    "email": "email",
    "e-mail": "email",
    "email address": "email",
    "full name": "full_name",
    "full_name": "full_name",
    "name": "full_name",
    "role": "role",
    "roll no": "roll_no",
    "roll no.": "roll_no",
    "roll_no": "roll_no",
    "roll number": "roll_no",
}
REQUIRED = ("email", "full_name", "role")

RowStatus = Literal["READY", "IMPORTED", "SKIPPED", "ERROR"]


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csv: str = Field(max_length=MAX_CHARS, description="The file's text, header row first")
    dry_run: bool = Field(description="True: only check and report. False: create the users")


class ImportRow(BaseModel):
    row: int = Field(description="Line number in the file (the header is line 1)")
    email: str
    full_name: str
    role: str
    roll_no: str | None
    status: RowStatus
    message: str | None = Field(description="Why the row is skipped or has an error")


class ImportResult(BaseModel):
    dry_run: bool
    total: int
    ready: int = Field(description="Rows that are (or would be) imported")
    skipped: int = Field(description="Emails that already have an account")
    failed: int = Field(description="Rows with errors; nothing is created for them")
    rows: list[ImportRow]


def _file_error(message: str) -> AppError:
    return AppError(
        "INVALID_FILE",
        message,
        status_code=422,
        details=[{"field": "csv", "message": message, "type": "file"}],
    )


def _parse(text: str) -> list[ImportRow]:
    """Rows of the file, each checked on its own (no database yet)."""
    # Excel adds a byte-order mark at the start; strict mode reports broken quoting.
    reader = csv.reader(io.StringIO(text.lstrip(BOM)), strict=True)
    try:
        header = next(reader)
    except StopIteration:
        raise _file_error("The file is empty.") from None
    except csv.Error as exc:
        raise _file_error(f"This isn't a readable CSV file ({exc}).") from exc
    columns = [HEADERS.get(h.strip().lower()) for h in header]
    missing = [name for name in REQUIRED if name not in columns]
    if missing:
        raise _file_error(
            "The first line must name the columns. Missing: "
            + ", ".join(m.replace("_", " ") for m in missing)
            + ". Expected: email, full name, role, roll no (optional)."
        )

    rows: list[ImportRow] = []
    try:
        for cells in reader:
            if not any(c.strip() for c in cells):
                continue  # blank line
            if len(rows) == MAX_ROWS:
                raise _file_error(f"The file has more than {MAX_ROWS:,} users. Split it up.")
            values = {
                column: cell.strip() for column, cell in zip(columns, cells, strict=False) if column
            }
            rows.append(_check(reader.line_num, values))
    except csv.Error as exc:
        raise _file_error(f"Line {reader.line_num} can't be read ({exc}).") from exc
    if not rows:
        raise _file_error("The file has a header but no users.")
    return rows


def _check(line: int, values: dict[str, str]) -> ImportRow:
    email, name = values.get("email", ""), values.get("full_name", "")
    role, roll_no = values.get("role", "").upper(), values.get("roll_no") or None
    problems = []
    try:
        email = validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError:
        problems.append("Email is not valid" if email else "Email is missing")
    if not name:
        problems.append("Name is missing")
    elif len(name) > 200:
        problems.append("Name is longer than 200 characters")
    if role not in ROLES:
        problems.append("Role must be Admin, Teacher or Student")
    if roll_no and len(roll_no) > 64:
        problems.append("Roll no. is longer than 64 characters")
    return ImportRow(
        row=line,
        email=email,
        full_name=name,
        role=role,
        roll_no=roll_no,
        status="ERROR" if problems else "READY",
        message="; ".join(problems) or None,
    )


async def _check_against_file_and_db(session: AsyncSession, rows: list[ImportRow]) -> None:
    """Duplicates inside the file, emails that already exist, roll numbers already used."""
    seen_email: dict[str, int] = {}
    seen_roll: dict[str, int] = {}
    for r in rows:
        if r.status != "READY":
            continue
        key = r.email.lower()
        if key in seen_email:
            r.status, r.message = "ERROR", f"Same email as line {seen_email[key]}"
            continue
        seen_email[key] = r.row
        if r.roll_no:
            if r.roll_no in seen_roll:
                r.status, r.message = "ERROR", f"Same roll no. as line {seen_roll[r.roll_no]}"
                continue
            seen_roll[r.roll_no] = r.row

    ready = [r for r in rows if r.status == "READY"]
    emails = [r.email.lower() for r in ready]
    existing = set(
        await session.scalars(
            select(func.lower(User.email)).where(func.lower(User.email).in_(emails))
        )
    )
    rolls = [r.roll_no for r in ready if r.roll_no]
    taken = set(await session.scalars(select(User.roll_no).where(User.roll_no.in_(rolls))))
    for r in ready:
        if r.email.lower() in existing:
            r.status, r.message = "SKIPPED", "Already has an account"
        elif r.roll_no in taken:
            r.status, r.message = "ERROR", f"Roll no. {r.roll_no} is already used by another user"


def _result(rows: list[ImportRow], dry_run: bool) -> ImportResult:
    def count(*statuses: str) -> int:
        return sum(r.status in statuses for r in rows)

    return ImportResult(
        dry_run=dry_run,
        total=len(rows),
        ready=count("READY", "IMPORTED"),
        skipped=count("SKIPPED"),
        failed=count("ERROR"),
        rows=rows,
    )


async def import_users(
    session: AsyncSession, principal: Principal, body: ImportRequest, base_url: str
) -> ImportResult:
    rows = _parse(body.csv)
    await _check_against_file_and_db(session, rows)
    if body.dry_run:
        return _result(rows, dry_run=True)

    ready = [r for r in rows if r.status == "READY"]
    institution = await session.get(Institution, principal.institution_id)
    institution_name = institution.name if institution else ""
    now = datetime.now(UTC)
    users = [
        User(email=r.email, full_name=r.full_name, role=r.role, status="INVITED", roll_no=r.roll_no)
        for r in ready
    ]
    session.add_all(users)
    try:
        await session.flush()
    except IntegrityError as exc:  # someone added one of these users since the check above
        await session.rollback()
        raise AppError(
            "CONFLICT",
            "Users were added while importing. Check the file again and retry.",
            status_code=409,
        ) from exc

    emails: list[Email] = []
    for user, r in zip(users, ready, strict=True):
        raw, hashed = new_opaque_token()  # new users have no older links to cancel
        session.add(
            AuthToken(
                institution_id=user.institution_id,
                user_id=user.id,
                purpose="INVITE",
                token_hash=hashed,
                expires_at=now + timedelta(days=INVITE_DAYS),
            )
        )
        emails.append(
            invitation_email(
                to=user.email,
                full_name=user.full_name,
                institution_name=institution_name,
                token=raw,
                base_url=base_url,
            )
        )
        record(
            session,
            "user.invited",
            institution_id=principal.institution_id,
            actor_id=principal.user_id,
            actor_role=principal.role,
            target_type="user",
            target_id=user.id,
            changes=diff({}, {"email": user.email, "role": user.role, "full_name": user.full_name}),
        )
        r.status = "IMPORTED"
    result = _result(rows, dry_run=False)
    record(
        session,
        "user.csv_imported",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        changes={"imported": result.ready, "skipped": result.skipped, "failed": result.failed},
    )
    await session.commit()
    for email in emails:
        queue_email(email)
    return result
