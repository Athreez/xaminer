"""Password hashing (Argon2id) and the password policy (PRD AUTH-07, SECURITY § 2.1)."""

from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 10
# Long inputs make hashing slow; a cap stops that being used to tie up the server.
MAX_LENGTH = 128

_hasher = PasswordHasher()  # argon2id with the library's current recommended parameters

_COMMON = frozenset(
    line.strip().lower()
    for line in (Path(__file__).with_name("common_passwords.txt"))
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip() and not line.startswith("#")
)


class WeakPasswordError(ValueError):
    """The password breaks the policy. The message is safe to show to the user."""


def check_policy(password: str, *, email: str = "", full_name: str = "") -> None:
    if len(password) < MIN_LENGTH:
        raise WeakPasswordError(f"Password must be at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        raise WeakPasswordError(f"Password must be at most {MAX_LENGTH} characters.")
    lowered = password.lower()
    if lowered in _COMMON:
        raise WeakPasswordError("This password is too common. Choose something less predictable.")
    if len(set(password)) < 4:
        raise WeakPasswordError("Password must not be mostly the same character.")
    personal = [email.split("@")[0], *full_name.split()]
    if any(len(part) >= 4 and part.lower() in lowered for part in personal):
        raise WeakPasswordError("Password must not contain your name or email.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the hash used older parameters; re-hash on the next successful login."""
    return _hasher.check_needs_rehash(password_hash)
