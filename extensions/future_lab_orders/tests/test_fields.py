"""Tests for due-date parsing and the task title."""

from datetime import date

import pytest

from future_lab_orders.fields import TASK_TITLE_MAX, parse_due_date, task_title


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-11-03", date(2026, 11, 3)),
        (" 2026-11-03 ", date(2026, 11, 3)),
        ("2026-11-03T00:00:00Z", date(2026, 11, 3)),
        ("11/3/2026", date(2026, 11, 3)),
        ("", None),
        (None, None),
        ("soon", None),
        ("13/45/2026", None),
    ],
)
def test_parse_due_date(raw: str | None, expected: date | None) -> None:
    assert parse_due_date(raw) == expected


def test_title_names_lab_and_tests() -> None:
    assert (
        task_title("Quest", "Lipid panel")
        == "Future lab order due: Quest - Lipid panel"
    )


def test_title_without_details() -> None:
    assert task_title("", "  ") == "Future lab order due"


def test_long_title_is_capped() -> None:
    title = task_title("Quest", "x" * 500)
    assert len(title) == TASK_TITLE_MAX
    assert title.endswith("...")
