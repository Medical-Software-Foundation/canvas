"""Patient metadata keys that hold a patient's future lab order.

A future lab order is three fields on the patient profile (lab, tests, due
date), stored as Canvas patient metadata. One more key, written only by the
daily job, records which due date already has a task, so the job never makes
two tasks for the same order. Changing the due date makes a new order.
"""

import re
from datetime import date, datetime

LAB_KEY = "future_lab_order_lab"
TESTS_KEY = "future_lab_order_tests"
DUE_DATE_KEY = "future_lab_order_due_date"
TASKED_FOR_KEY = "future_lab_order_task_created_for"

ALL_KEYS = (LAB_KEY, TESTS_KEY, DUE_DATE_KEY, TASKED_FOR_KEY)

TASK_TITLE_MAX = 250

_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def parse_due_date(raw: str | None) -> date | None:
    """Parse the stored due date. Accepts YYYY-MM-DD (with or without a time) or MM/DD/YYYY."""
    value = (raw or "").strip()
    if not value:
        return None
    us = _US_DATE.match(value)
    try:
        if us:
            return date(int(us.group(3)), int(us.group(1)), int(us.group(2)))
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def task_title(lab: str, tests: str) -> str:
    """Build the task title from the order, capped at TASK_TITLE_MAX characters."""
    parts = [p for p in (lab.strip(), tests.strip()) if p]
    title = "Future lab order due"
    if parts:
        title += ": " + " - ".join(parts)
    if len(title) > TASK_TITLE_MAX:
        title = title[: TASK_TITLE_MAX - 3].rstrip() + "..."
    return title
