import pytest

from app.auth.passwords import (
    WeakPasswordError,
    check_policy,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_hash_and_verify() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery")
    assert not verify_password(hashed, "correct horse battery!")
    assert not needs_rehash(hashed)


def test_same_password_gets_different_hashes() -> None:
    assert hash_password("correct horse battery") != hash_password("correct horse battery")


def test_garbage_hash_is_just_a_failed_check() -> None:
    assert not verify_password("not-a-hash", "whatever123")


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("short1", "at least 10"),
        ("x" * 129, "at most 128"),
        ("Password123", "too common"),
        ("QWERTYUIOP", "too common"),
        ("aaaaaaaaaaab", "same character"),
        ("asha.rao-2026!", "your name or email"),
        ("myAsha1234!!", "your name or email"),
    ],
)
def test_policy_rejects(password: str, reason: str) -> None:
    with pytest.raises(WeakPasswordError, match=reason):
        check_policy(password, email="asha.rao@abc.edu", full_name="Asha Rao")


def test_policy_accepts_reasonable_password() -> None:
    check_policy("violet-tram-42-lantern", email="asha.rao@abc.edu", full_name="Asha Rao")
