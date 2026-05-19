"""Shared fixtures for the vitals-dashboard test suite."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def session_dt():
    return datetime(2026, 4, 22, 14, 30, tzinfo=timezone.utc)


@pytest.fixture
def mock_session(session_dt):
    s = MagicMock()
    s.dbid = 101
    s.patient_key = "patient-abc"
    s.note_id = ""
    s.entered_by_staff_key = "staff-1"
    s.provider_of_record_key = "staff-2"
    s.session_datetime = session_dt
    s.note_stale = False
    s.observations_synced = False
    return s


def make_measurement(
    vital_type,
    value_numeric=None,
    value_text="",
    position="",
    cuff_location="",
    recorded_at=None,
    session_id="101",
    patient_key="patient-abc",
    dbid=1,
    is_deleted=False,
    entered_by_staff_key="staff-1",
    unit="",
):
    m = MagicMock()
    m.dbid = dbid
    m.session_id = session_id
    m.patient_key = patient_key
    m.vital_type = vital_type
    m.position = position
    m.cuff_location = cuff_location
    m.value_numeric = Decimal(str(value_numeric)) if value_numeric is not None else None
    m.value_text = value_text
    m.unit = unit
    m.recorded_at = recorded_at
    m.is_deleted = is_deleted
    m.entered_by_staff_key = entered_by_staff_key
    return m


@pytest.fixture
def measurement_factory():
    return make_measurement


@pytest.fixture
def mock_request():
    """Blank request mock — tests should populate .json/.query_params/.path_params/.headers per need."""
    req = MagicMock()
    req.headers = {}
    req.query_params = {}
    req.path_params = {}
    req.json.return_value = {}
    return req
