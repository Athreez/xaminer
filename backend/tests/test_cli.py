"""platform-admin behaviour that doesn't need a database: the password prompt."""

import getpass
from collections.abc import Callable

import pytest

from cli.__main__ import main

ADMIN_ARGS = ["create-admin", "--institution", "X", "--email", "a@x.edu", "--name", "A B"]


def _prompt_raising(exc: type[BaseException]) -> Callable[[str], str]:
    def fake(prompt: str = "") -> str:
        raise exc

    return fake


def test_ctrl_c_at_password_prompt_cancels_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(getpass, "getpass", _prompt_raising(KeyboardInterrupt))
    assert main(ADMIN_ARGS) == 130
    err = capsys.readouterr().err
    assert "Cancelled." in err
    assert "Traceback" not in err


def test_no_terminal_gives_clear_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(getpass, "getpass", _prompt_raising(EOFError))
    assert main(ADMIN_ARGS) == 1
    assert "No password entered" in capsys.readouterr().err


def test_mismatched_passwords(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = iter(["first-password-1", "second-password-2"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(answers))
    assert main(ADMIN_ARGS) == 1
    assert "don't match" in capsys.readouterr().err
