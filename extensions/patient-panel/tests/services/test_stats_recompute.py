__is_plugin__ = True

import pytest
from canvas_sdk.test_utils.factories import PatientFactory, TaskFactory

from patient_panel.models import PatientPanelStats
from patient_panel.services.stats_recompute import (
    compute_stat_values,
    recompute_stats_for_patient,
)

pytestmark = pytest.mark.django_db


def test_recompute_creates_row_with_defaults_for_empty_patient() -> None:
    p = PatientFactory.create()
    recompute_stats_for_patient(p.dbid)
    row = PatientPanelStats.objects.get(patient_id=p.dbid)
    assert row.tasks_open_count == 0
    assert row.gaps_due_count == 0
    assert row.last_visit_dt is None
    assert row.room_number is None
    assert row.next_visit_dt is None


def test_recompute_counts_open_tasks() -> None:
    p = PatientFactory.create()
    TaskFactory.create(patient=p, status="OPEN")
    TaskFactory.create(patient=p, status="OPEN")
    recompute_stats_for_patient(p.dbid)
    assert PatientPanelStats.objects.get(patient_id=p.dbid).tasks_open_count == 2


def test_recompute_is_idempotent() -> None:
    p = PatientFactory.create()
    recompute_stats_for_patient(p.dbid)
    recompute_stats_for_patient(p.dbid)
    assert PatientPanelStats.objects.filter(patient_id=p.dbid).count() == 1


def test_compute_stat_values_shape() -> None:
    p = PatientFactory.create()
    vals = compute_stat_values(p.dbid)
    assert set(vals) == {
        "last_visit_dt",
        "next_visit_dt",
        "room_number",
        "tasks_open_count",
        "gaps_due_count",
    }
