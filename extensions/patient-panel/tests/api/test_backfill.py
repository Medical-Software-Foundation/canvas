"""Tests for the POST /stats/backfill endpoint."""

__is_plugin__ = True

import json

import pytest

from canvas_sdk.test_utils.factories import PatientFactory, TaskFactory
from canvas_sdk.v1.data import Patient

from patient_panel.models import PatientPanelStats
from tests._helpers import build_api

pytestmark = pytest.mark.django_db


def test_backfill_endpoint_populates_all_patients() -> None:
    p1 = PatientFactory.create()
    p2 = PatientFactory.create()
    TaskFactory.create(patient=p1, status="OPEN")
    api = build_api(headers={"canvas-logged-in-user-id": ""})
    result = api.backfill_stats()
    assert result[0].status_code == 200
    body = json.loads(result[0].content)
    assert body["status"] == "ok"
    assert body["patients"] >= 2
    assert PatientPanelStats.objects.filter(patient_id=p1.dbid).get().tasks_open_count == 1
    assert PatientPanelStats.objects.filter(patient_id=p2.dbid).exists()


def test_backfill_endpoint_is_idempotent() -> None:
    PatientFactory.create()
    api = build_api(headers={"canvas-logged-in-user-id": ""})
    api.backfill_stats()
    api.backfill_stats()
    # one row per patient regardless of repeated calls
    assert PatientPanelStats.objects.count() == Patient.objects.count()
