__is_plugin__ = True

import arrow
import pytest

from canvas_sdk.test_utils.factories import PatientFactory, TaskFactory

from tests.factories import PatientPanelStatsFactory
from patient_panel.models import PatientPanelStats
from patient_panel.handlers.panel_stats_reconcile import reconcile_all_stats

pytestmark = pytest.mark.django_db


def test_stats_table_is_usable() -> None:
    PatientPanelStatsFactory.create(tasks_open_count=3)
    assert PatientPanelStats.objects.filter(tasks_open_count=3).count() == 1


def test_reconcile_creates_rows_for_all_patients() -> None:
    p1 = PatientFactory.create()
    p2 = PatientFactory.create()
    TaskFactory.create(patient=p1, status="OPEN")
    reconcile_all_stats()
    assert PatientPanelStats.objects.count() == 2
    assert PatientPanelStats.objects.get(patient_id=p1.dbid).tasks_open_count == 1
    assert PatientPanelStats.objects.get(patient_id=p2.dbid).tasks_open_count == 0


def test_reconcile_repairs_stale_row() -> None:
    p = PatientFactory.create()
    PatientPanelStats.objects.create(
        patient_id=p.dbid, tasks_open_count=99, room_number="",
        updated=arrow.utcnow().datetime,
    )
    TaskFactory.create(patient=p, status="OPEN")
    reconcile_all_stats()
    assert PatientPanelStats.objects.get(patient_id=p.dbid).tasks_open_count == 1


def test_reconcile_creates_default_row_for_patient_without_data() -> None:
    p = PatientFactory.create()
    reconcile_all_stats()
    row = PatientPanelStats.objects.get(patient_id=p.dbid)
    assert row.tasks_open_count == 0
    assert row.gaps_due_count == 0
    assert row.last_visit_dt is None


def test_reconcile_bulk_matches_per_patient() -> None:
    from patient_panel.services.stats_recompute import compute_stat_values

    p1 = PatientFactory.create()
    p2 = PatientFactory.create()
    TaskFactory.create(patient=p1, status="OPEN")
    TaskFactory.create(patient=p1, status="OPEN")
    reconcile_all_stats()
    for p in (p1, p2):
        row = PatientPanelStats.objects.get(patient_id=p.dbid)
        expected = compute_stat_values(p.dbid)
        assert row.tasks_open_count == expected["tasks_open_count"]
        assert row.gaps_due_count == expected["gaps_due_count"]
        assert row.last_visit_dt == expected["last_visit_dt"]
        assert row.next_visit_dt == expected["next_visit_dt"]
        assert (row.room_number or None) == (expected["room_number"] or None)
