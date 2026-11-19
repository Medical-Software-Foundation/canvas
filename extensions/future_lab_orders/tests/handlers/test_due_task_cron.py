"""Behavior tests for the daily future lab order job."""

import json
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.test_utils.factories import PatientFactory, TeamFactory
from canvas_sdk.v1.data.patient import PatientMetadata

from future_lab_orders.fields import DUE_DATE_KEY, LAB_KEY, TASKED_FOR_KEY, TESTS_KEY
from future_lab_orders.handlers import due_task_cron
from future_lab_orders.handlers.due_task_cron import FutureLabOrderDueTasks, due_orders

TODAY = date(2026, 11, 3)
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def set_order(
    patient: Any,
    due: str,
    lab: str = "Quest",
    tests: str = "CBC, CMP",
    tasked_for: str | None = None,
) -> None:
    rows = {LAB_KEY: lab, TESTS_KEY: tests, DUE_DATE_KEY: due}
    if tasked_for is not None:
        rows[TASKED_FOR_KEY] = tasked_for
    for key, value in rows.items():
        PatientMetadata.objects.create(patient=patient, key=key, value=value)


def run(secrets: dict[str, str] | None = None) -> list[Any]:
    with patch.object(due_task_cron, "datetime") as fake_datetime:
        fake_datetime.now.return_value = NOW
        return FutureLabOrderDueTasks(event=None, secrets=secrets or {}).execute()  # type: ignore[arg-type]


def payloads(effects: list[Any], effect_type: int) -> list[dict[str, Any]]:
    return [json.loads(e.payload) for e in effects if e.type == effect_type]


@pytest.mark.django_db
def test_order_due_today_creates_task_and_marks_it() -> None:
    patient = PatientFactory.create()
    set_order(patient, "2026-11-03")

    effects = run()

    tasks = payloads(effects, EffectType.CREATE_TASK)
    assert len(tasks) == 1
    task = tasks[0]["data"]
    assert task["patient"] == {"id": patient.id}
    assert task["title"] == "Future lab order due: Quest - CBC, CMP"
    assert task["status"] == "OPEN"
    assert task["labels"] == ["future lab order"]
    assert task["due"].startswith("2026-11-03")

    marks = payloads(effects, EffectType.UPSERT_PATIENT_METADATA)
    assert marks == [
        {
            "data": {
                "patient_id": patient.id,
                "key": TASKED_FOR_KEY,
                "value": "2026-11-03",
            }
        }
    ]


@pytest.mark.django_db
def test_future_order_is_left_alone() -> None:
    set_order(PatientFactory.create(), "2026-11-04")

    assert run() == []


@pytest.mark.django_db
def test_overdue_order_without_task_is_caught_up() -> None:
    patient = PatientFactory.create()
    set_order(patient, "10/30/2026")

    effects = run()

    assert len(payloads(effects, EffectType.CREATE_TASK)) == 1
    assert (
        payloads(effects, EffectType.UPSERT_PATIENT_METADATA)[0]["data"]["value"]
        == "10/30/2026"
    )


@pytest.mark.django_db
def test_order_already_tasked_is_not_tasked_again() -> None:
    set_order(PatientFactory.create(), "2026-11-03", tasked_for="2026-11-03")

    assert run() == []


@pytest.mark.django_db
def test_new_due_date_after_a_task_makes_a_new_task() -> None:
    patient = PatientFactory.create()
    set_order(patient, "2026-11-03", tasked_for="2026-08-01")

    assert len(payloads(run(), EffectType.CREATE_TASK)) == 1


@pytest.mark.django_db
def test_inactive_patient_and_bad_dates_are_skipped() -> None:
    set_order(PatientFactory.create(active=False), "2026-11-01")
    set_order(PatientFactory.create(), "not a date")
    set_order(PatientFactory.create(), "")

    assert run() == []


@pytest.mark.django_db
def test_team_setting_assigns_the_task() -> None:
    team = TeamFactory.create(name="Lab Team")
    set_order(PatientFactory.create(), "2026-11-03")

    task = payloads(run({"FUTURE_LAB_TASK_TEAM": "Lab Team"}), EffectType.CREATE_TASK)[
        0
    ]

    assert task["data"]["team"] == {"id": str(team.id)}


@pytest.mark.django_db
def test_unknown_team_leaves_task_unassigned() -> None:
    set_order(PatientFactory.create(), "2026-11-03")

    task = payloads(
        run({"FUTURE_LAB_TASK_TEAM": "No Such Team"}), EffectType.CREATE_TASK
    )[0]

    assert task["data"]["team"] == {"id": None}


@pytest.mark.django_db
def test_run_is_capped_oldest_first() -> None:
    oldest = PatientFactory.create()
    set_order(oldest, "2026-10-01")
    set_order(PatientFactory.create(), "2026-11-02")

    with patch.object(due_task_cron, "MAX_TASKS_PER_RUN", 1):
        effects = run()

    tasks = payloads(effects, EffectType.CREATE_TASK)
    assert [t["data"]["patient"] for t in tasks] == [{"id": oldest.id}]


@pytest.mark.django_db
def test_due_orders_uses_a_fixed_number_of_queries(
    django_assert_num_queries: Any,
) -> None:
    for _ in range(5):
        set_order(PatientFactory.create(), "2026-11-01")

    with django_assert_num_queries(2):
        orders = due_orders(TODAY)

    assert len(orders) == 5
