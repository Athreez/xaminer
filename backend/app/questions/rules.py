"""What a valid question of each type looks like (PRD QB-02 to QB-05).

Checked on create and on every edit, against the version as it will be saved, so a PATCH can't
leave a question in a shape the exam screen and grader don't understand. Errors name the field.
"""

from decimal import Decimal
from typing import Any

from app.core.errors import AppError
from app.questions.schemas import OptionIn

MIN_OPTIONS, MAX_OPTIONS = 2, 10
TRUE_FALSE = ("True", "False")
CHOICE_TYPES = ("MCQ", "MSQ", "TRUE_FALSE")


def check(type: str, content: dict[str, Any], options: list[OptionIn]) -> list[OptionIn]:
    """Raise VALIDATION_FAILED listing every problem, or return the options to save.

    `content` is the version's fields and is completed in place (MSQ scoring defaults to
    ALL_OR_NOTHING). True/False labels come back in their fixed spelling and order.
    """
    errors: list[tuple[str, str]] = []

    def wrong(field: str, message: str) -> None:
        errors.append((field, message))

    points: Decimal = content["points"]
    if content["negative_marks"] > points:
        wrong("negative_marks", "Negative marks can't be more than the question's points.")

    if type == "MSQ":
        content["msq_scoring"] = content["msq_scoring"] or "ALL_OR_NOTHING"
    elif content["msq_scoring"] is not None:
        wrong("msq_scoring", "Only multiple-select questions have a scoring mode.")
    if type != "DESCRIPTIVE":
        if content["rubric"]:
            wrong("rubric", "Only descriptive questions have a rubric.")
        if content["max_answer_length"] is not None:
            wrong("max_answer_length", "Only descriptive questions have an answer length limit.")

    if type not in CHOICE_TYPES:
        if options:
            wrong("options", "This type of question has no options.")
    else:
        options = _check_options(type, options, wrong)

    if errors:
        raise AppError(
            "VALIDATION_FAILED",
            errors[0][1],
            status_code=422,
            details=[{"field": f, "message": m, "type": "question_rule"} for f, m in errors],
        )
    return options


def _check_options(type: str, options: list[OptionIn], wrong) -> list[OptionIn]:  # type: ignore[no-untyped-def]
    correct = sum(o.is_correct for o in options)
    if type == "TRUE_FALSE":
        labels = tuple(o.label.strip().lower() for o in options)
        if labels != ("true", "false"):
            wrong("options", 'True/False questions have exactly two options: "True", then "False".')
            return options
        if correct != 1:
            wrong("options", "Mark either True or False as the correct answer.")
        return [
            OptionIn(label=label, is_correct=o.is_correct)
            for label, o in zip(TRUE_FALSE, options, strict=True)
        ]

    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        wrong("options", f"Give between {MIN_OPTIONS} and {MAX_OPTIONS} options.")
    seen: dict[str, int] = {}
    for i, option in enumerate(options):
        key = " ".join(option.label.lower().split())
        if key in seen:
            wrong(f"options.{i}.label", f"Option {i + 1} is the same as option {seen[key] + 1}.")
        seen.setdefault(key, i)
    if type == "MCQ" and correct != 1:
        wrong("options", "Mark exactly one option as correct.")
    if type == "MSQ" and correct < 1:
        wrong("options", "Mark at least one option as correct.")
    return options
