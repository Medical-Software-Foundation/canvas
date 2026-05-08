"""Tests for api/scheduling_api.py."""

import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from scheduling_with_rooms.api.scheduling_api import (
    SchedulingAPI,
    _allowed_room_keys_for,
)


def _handler(body=None, query_params=None, secrets=None):
    h = SchedulingAPI.__new__(SchedulingAPI)
    request = MagicMock()
    request.json.return_value = body if body is not None else {}
    request.query_params = query_params or {}
    h.request = request
    h.secrets = secrets if secrets is not None else {"SCHEDULABLE_STAFF_ROLES": "MD,NP"}
    return h


# _allowed_room_keys_for ------------------------------------------------

def test_allowed_room_keys_empty_code():
    assert _allowed_room_keys_for("") is None


def test_allowed_room_keys_no_rows_returns_none():
    with patch(
        "scheduling_with_rooms.api.scheduling_api.VisitTypeRoomMapping"
    ) as mock_m:
        mock_m.objects.filter.return_value.values_list.return_value = []
        assert _allowed_room_keys_for("VISIT") is None


def test_allowed_room_keys_with_rows_returns_set():
    with patch(
        "scheduling_with_rooms.api.scheduling_api.VisitTypeRoomMapping"
    ) as mock_m:
        mock_m.objects.filter.return_value.values_list.return_value = ["r1", "r2"]
        result = _allowed_room_keys_for("VISIT")
        assert result == {"r1", "r2"}


# Helper methods --------------------------------------------------------

def test_fhir_client_construction():
    h = _handler(secrets={
        "FHIR_BASE_URL": "https://fumage-x.canvasmedical.com",
        "FHIR_CLIENT_ID": "id",
        "FHIR_CLIENT_SECRET": "secret",
    })
    with patch("scheduling_with_rooms.api.scheduling_api.FHIRClient") as mock_cls:
        mock_cls.return_value = MagicMock(name="client")
        result = h._fhir_client()
        assert result is mock_cls.return_value


def test_schedulable_roles_parses_secret():
    h = _handler(secrets={"SCHEDULABLE_STAFF_ROLES": "MD,NP"})
    assert h._schedulable_roles() == ["MD", "NP"]


def test_location_name_found():
    h = _handler()
    with patch(
        "scheduling_with_rooms.api.scheduling_api.PracticeLocation"
    ) as mock_pl:
        mock_pl.objects.filter.return_value.values.return_value.first.return_value = {
            "full_name": "Office"
        }
        assert h._location_name("loc-1") == "Office"


def test_location_name_missing():
    h = _handler()
    with patch(
        "scheduling_with_rooms.api.scheduling_api.PracticeLocation"
    ) as mock_pl:
        mock_pl.objects.filter.return_value.values.return_value.first.return_value = None
        assert h._location_name("loc-1") == ""


# /modal ----------------------------------------------------------------

def test_modal_no_patient_id():
    h = _handler(query_params={"patient_id": ""})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.render_to_string",
        return_value="<html>",
    ):
        result = h.modal()
        assert len(result) == 1


def test_modal_with_patient_id_found():
    h = _handler(query_params={"patient_id": "pt-1"})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.Patient"
    ) as mock_pt, patch(
        "scheduling_with_rooms.api.scheduling_api.render_to_string",
        return_value="<html>",
    ):
        mock_pt.objects.filter.return_value.values.return_value.first.return_value = {
            "id": "pt-1",
            "first_name": "Bob",
            "last_name": "Smith",
            "birth_date": datetime.date(2000, 1, 15),
            "last_known_timezone": "America/New_York",
        }
        result = h.modal()
        assert len(result) == 1


def test_modal_with_patient_id_not_found():
    h = _handler(query_params={"patient_id": "pt-1"})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.Patient"
    ) as mock_pt, patch(
        "scheduling_with_rooms.api.scheduling_api.render_to_string",
        return_value="<html>",
    ):
        mock_pt.objects.filter.return_value.values.return_value.first.return_value = None
        result = h.modal()
        assert len(result) == 1


def test_modal_with_patient_no_dob():
    h = _handler(query_params={"patient_id": "pt-1"})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.Patient"
    ) as mock_pt, patch(
        "scheduling_with_rooms.api.scheduling_api.render_to_string",
        return_value="<html>",
    ):
        mock_pt.objects.filter.return_value.values.return_value.first.return_value = {
            "id": "pt-1",
            "first_name": "Bob",
            "last_name": "Smith",
            "birth_date": None,
            "last_known_timezone": None,
        }
        result = h.modal()
        assert len(result) == 1


# /patients -------------------------------------------------------------

def test_patients_short_query_returns_400():
    h = _handler(query_params={"q": ""})
    result = h.patients()
    assert len(result) == 1


def test_patients_returns_results_with_fhir_tz():
    h = _handler(query_params={"q": "bob"})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.Patient"
    ) as mock_pt, patch(
        "scheduling_with_rooms.api.scheduling_api.FHIRClient"
    ) as mock_fhir_cls:
        first_match = {
            "id": "pt-1",
            "first_name": "Bob",
            "last_name": "Smith",
            "birth_date": datetime.date(2000, 1, 15),
            "last_known_timezone": "America/New_York",
        }
        last_match = {
            "id": "pt-2",
            "first_name": "Alice",
            "last_name": "Bob",  # last name "Bob"
            "birth_date": None,
            "last_known_timezone": None,
        }
        # Patient.objects.filter().values()[:20] returns lists.
        mock_pt.objects.filter.return_value.values.return_value.__getitem__.side_effect = [
            [first_match, first_match],  # first_name search (with dup for dedupe)
            [last_match],
        ]
        mock_fhir = MagicMock()
        mock_fhir.get_patient_timezones.return_value = {"pt-1": "America/Chicago"}
        mock_fhir_cls.return_value = mock_fhir

        result = h.patients()
        assert len(result) == 1


def test_patients_fhir_failure_swallows_exception():
    h = _handler(query_params={"q": "bob"})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.Patient"
    ) as mock_pt, patch(
        "scheduling_with_rooms.api.scheduling_api.FHIRClient"
    ) as mock_fhir_cls:
        mock_pt.objects.filter.return_value.values.return_value.__getitem__.side_effect = [
            [{"id": "pt-1", "first_name": "Bob", "last_name": "Smith", "birth_date": None, "last_known_timezone": ""}],
            [],
        ]
        mock_fhir_cls.return_value.get_patient_timezones.side_effect = (
            requests.RequestException("boom")
        )
        result = h.patients()
        assert len(result) == 1


def test_patients_no_results_skips_fhir():
    h = _handler(query_params={"q": "bob"})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.Patient"
    ) as mock_pt:
        mock_pt.objects.filter.return_value.values.return_value.__getitem__.side_effect = [
            [], []
        ]
        result = h.patients()
        assert len(result) == 1


# /patient-timezone -----------------------------------------------------

def test_patient_timezone_missing_id_returns_400():
    h = _handler(query_params={"patient_id": ""})
    result = h.patient_timezone()
    assert len(result) == 1


def test_patient_timezone_returns_value():
    h = _handler(query_params={"patient_id": "pt-1"})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.FHIRClient"
    ) as mock_fhir_cls:
        mock_fhir_cls.return_value.get_patient_timezone.return_value = "America/New_York"
        result = h.patient_timezone()
        assert len(result) == 1


# /locations ------------------------------------------------------------

def test_locations_returns_active():
    h = _handler()
    with patch(
        "scheduling_with_rooms.api.scheduling_api.PracticeLocation"
    ) as mock_pl:
        mock_pl.objects.filter.return_value.values.return_value = [
            {"id": "loc-1", "full_name": "A"},
        ]
        result = h.locations()
        assert len(result) == 1


# /providers ------------------------------------------------------------

def test_providers_no_roles():
    h = _handler(secrets={"SCHEDULABLE_STAFF_ROLES": ""})
    result = h.providers()
    assert len(result) == 1


def test_providers_location_id_not_found():
    h = _handler(query_params={"location_id": "loc-bad"})
    with patch.object(h.__class__, "_location_name", return_value=""):
        result = h.providers()
        assert len(result) == 1


def test_providers_location_match():
    h = _handler(query_params={"location_id": "loc-1"})
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_providers_for_location",
        return_value=[{"id": "p1", "name": "Bob"}],
    ):
        result = h.providers()
        assert len(result) == 1


def test_providers_all_locations_dedupes():
    h = _handler(query_params={"location_id": ""})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.PracticeLocation"
    ) as mock_pl, patch(
        "scheduling_with_rooms.api.scheduling_api.get_providers_for_location",
    ) as mock_gp, patch(
        "scheduling_with_rooms.api.scheduling_api._fetch_clinic_calendars",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.api.scheduling_api._fetch_schedulable_staff",
        return_value=[],
    ):
        mock_pl.objects.filter.return_value.order_by.return_value.values_list.return_value = [
            "L1",
            "L2",
        ]
        mock_gp.side_effect = [
            [{"id": "p1", "name": "Bob"}],
            [{"id": "p1", "name": "Bob"}, {"id": "p2", "name": "Alice"}],
        ]
        result = h.providers()
        assert len(result) == 1


# /note-types ----------------------------------------------------------

def test_note_types_returns_active():
    h = _handler()
    with patch(
        "scheduling_with_rooms.api.scheduling_api.NoteType"
    ) as mock_nt:
        mock_nt.objects.filter.return_value.order_by.return_value.values.return_value = [
            {"id": "nt-1", "name": "Visit", "code": "VISIT"},
        ]
        result = h.note_types()
        assert len(result) == 1


# /durations ------------------------------------------------------------

def test_durations_per_visit_type_match():
    h = _handler(query_params={"note_type_code": "VISIT"})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.get_durations_for",
        return_value=[30, 60],
    ):
        result = h.durations()
        assert len(result) == 1


def test_durations_secret_json_array():
    h = _handler(
        query_params={},
        secrets={"SCHEDULE_DURATIONS": "[15, 30, 45]"},
    )
    result = h.durations()
    assert len(result) == 1


def test_durations_secret_csv():
    h = _handler(
        query_params={},
        secrets={"SCHEDULE_DURATIONS": "10,20,30"},
    )
    result = h.durations()
    assert len(result) == 1


def test_durations_secret_json_non_list_falls_back_to_csv():
    # JSON is "30" — a single number, not a list. Falls through to CSV path.
    h = _handler(
        query_params={},
        secrets={"SCHEDULE_DURATIONS": '"30,60"'},
    )
    result = h.durations()
    assert len(result) == 1


def test_durations_secret_invalid_json_handled():
    # Not JSON, not parseable as int CSV.
    h = _handler(
        query_params={},
        secrets={"SCHEDULE_DURATIONS": "garbage"},
    )
    result = h.durations()
    assert len(result) == 1


def test_durations_secret_outer_exception_handled():
    h = _handler(
        query_params={},
        secrets={"SCHEDULE_DURATIONS": "30"},
    )
    # Force outer exception by killing JSONResponse import-side: monkeypatch json
    with patch(
        "scheduling_with_rooms.api.scheduling_api.JSONResponse"
    ) as mock_resp:
        mock_resp.return_value = "resp"
        result = h.durations()
        assert len(result) == 1


def test_durations_fallback_defaults():
    h = _handler(query_params={}, secrets={})
    result = h.durations()
    assert len(result) == 1


def test_durations_visit_type_no_config_falls_through():
    h = _handler(query_params={"note_type_code": "VISIT"})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.get_durations_for",
        return_value=[],
    ):
        result = h.durations()
        assert len(result) == 1


# /month-summary --------------------------------------------------------

def test_month_summary_missing_params():
    h = _handler(query_params={})
    result = h.month_summary()
    assert len(result) == 1


def test_month_summary_invalid_year_month():
    h = _handler(query_params={
        "location_id": "loc-1",
        "year_month": "bad",
        "duration": "30",
    })
    result = h.month_summary()
    assert len(result) == 1


def test_month_summary_with_provider_filter():
    h = _handler(query_params={
        "location_id": "loc-1",
        "year_month": "2026-05",
        "duration": "30",
        "provider_id": "p1",
    })
    staff = MagicMock()
    staff.full_name = "Bob"
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.Staff"
    ) as mock_staff, patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value=None,
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.build_month_slot_counts",
        return_value={"2026-05-01": 5},
    ):
        mock_staff.objects.filter.return_value.first.return_value = staff
        result = h.month_summary()
        assert len(result) == 1


def test_month_summary_no_providers_uses_utc():
    h = _handler(query_params={
        "location_id": "loc-1",
        "year_month": "2026-05",
        "duration": "30",
    })
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_providers_for_location",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value=None,
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.build_month_slot_counts",
        return_value={},
    ):
        result = h.month_summary()
        assert len(result) == 1


def test_month_summary_no_schedulable_roles():
    h = _handler(
        query_params={
            "location_id": "loc-1",
            "year_month": "2026-05",
            "duration": "30",
        },
        secrets={"SCHEDULABLE_STAFF_ROLES": ""},
    )
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value=None,
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.build_month_slot_counts",
        return_value={},
    ):
        result = h.month_summary()
        assert len(result) == 1


def test_month_summary_compute_failure_propagates():
    """Local removed the try/except wrapper around build_month_slot_counts —
    failures now propagate to the caller instead of producing a 500."""
    h = _handler(query_params={
        "location_id": "loc-1",
        "year_month": "2026-05",
        "duration": "30",
    })
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_providers_for_location",
        return_value=[{"id": "p1", "name": "Bob"}],
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value=None,
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.build_month_slot_counts",
        side_effect=RuntimeError("boom"),
    ), pytest.raises(RuntimeError):
        h.month_summary()


# /all-slots ------------------------------------------------------------

def test_all_slots_missing_params():
    h = _handler(query_params={})
    result = h.all_slots()
    assert len(result) == 1


def test_all_slots_invalid_duration():
    h = _handler(query_params={
        "location_id": "loc-1",
        "date": "2026-05-07",
        "duration": "abc",
    })
    result = h.all_slots()
    assert len(result) == 1


def test_all_slots_with_provider_filter_and_no_rooms():
    h = _handler(query_params={
        "location_id": "loc-1",
        "date": "2026-05-07",
        "duration": "30",
        "provider_id": "p1",
    })
    staff = MagicMock()
    staff.full_name = "Bob"
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.Staff"
    ) as mock_staff, patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.build_all_provider_slots",
        return_value=[{"id": "p1", "name": "Bob", "slots": []}],
    ), patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value=None,
    ):
        mock_staff.objects.filter.return_value.first.return_value = staff
        result = h.all_slots()
        assert len(result) == 1


def test_all_slots_with_room_keys():
    h = _handler(query_params={
        "location_id": "loc-1",
        "date": "2026-05-07",
        "duration": "30",
        "note_type_code": "VISIT",
    })
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_providers_for_location",
        return_value=[{"id": "p1", "name": "Bob"}],
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.build_all_provider_slots",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value={"r1"},
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.build_all_room_slots",
        return_value=[{"id": "r1", "name": "Exam 1", "slots": []}],
    ):
        result = h.all_slots()
        assert len(result) == 1


def test_all_slots_room_failure_propagates():
    """Local removed the try/except wrapper around build_all_room_slots —
    failures now propagate instead of being swallowed into empty rooms."""
    h = _handler(query_params={
        "location_id": "loc-1",
        "date": "2026-05-07",
        "duration": "30",
        "note_type_code": "VISIT",
    })
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_providers_for_location",
        return_value=[{"id": "p1", "name": "Bob"}],
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.build_all_provider_slots",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value={"r1"},
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.build_all_room_slots",
        side_effect=RuntimeError("boom"),
    ), pytest.raises(RuntimeError):
        h.all_slots()


def test_all_slots_provider_failure_propagates():
    """Local removed the try/except wrapper around build_all_provider_slots —
    failures now propagate instead of producing a 500."""
    h = _handler(query_params={
        "location_id": "loc-1",
        "date": "2026-05-07",
        "duration": "30",
    })
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_providers_for_location",
        return_value=[{"id": "p1", "name": "Bob"}],
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.build_all_provider_slots",
        side_effect=RuntimeError("boom"),
    ), pytest.raises(RuntimeError):
        h.all_slots()


def test_all_slots_no_providers_uses_utc():
    h = _handler(
        query_params={
            "location_id": "loc-1",
            "date": "2026-05-07",
            "duration": "30",
        },
        secrets={"SCHEDULABLE_STAFF_ROLES": ""},
    )
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.build_all_provider_slots",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value=None,
    ):
        result = h.all_slots()
        assert len(result) == 1


# /slots ----------------------------------------------------------------

def test_slots_missing_params():
    h = _handler(query_params={})
    result = h.slots()
    assert len(result) == 1


def test_slots_invalid_duration():
    h = _handler(query_params={
        "provider_id": "p1",
        "location_id": "loc-1",
        "date": "2026-05-07",
        "duration": "abc",
    })
    result = h.slots()
    assert len(result) == 1


def test_slots_no_rooms_path():
    h = _handler(query_params={
        "provider_id": "p1",
        "location_id": "loc-1",
        "date": "2026-05-07",
        "duration": "30",
    })
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value=None,
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.build_plain_slots",
        return_value=[],
    ):
        result = h.slots()
        assert len(result) == 1


def test_slots_with_rooms_path():
    h = _handler(query_params={
        "provider_id": "p1",
        "location_id": "loc-1",
        "date": "2026-05-07",
        "duration": "30",
        "note_type_code": "VISIT",
    })
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value={"r1"},
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.build_slots_with_resource_availability",
        return_value=[],
    ):
        result = h.slots()
        assert len(result) == 1


def test_slots_failure_propagates():
    """Local removed the try/except wrapper around build_plain_slots —
    failures now propagate instead of producing a 500."""
    h = _handler(query_params={
        "provider_id": "p1",
        "location_id": "loc-1",
        "date": "2026-05-07",
        "duration": "30",
    })
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value=None,
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.build_plain_slots",
        side_effect=RuntimeError("boom"),
    ), pytest.raises(RuntimeError):
        h.slots()


# /book -----------------------------------------------------------------

def test_book_missing_fields():
    h = _handler({})
    result = h.book()
    assert len(result) == 1


def test_book_basic_naive_start_time():
    h = _handler({
        "patient_id": "pt-1",
        "provider_id": "p1",
        "location_id": "loc-1",
        "note_type_id": "nt-1",
        "note_type_code": "VISIT",
        "start_time": "2026-05-07T10:00:00",
        "duration_minutes": 30,
    })
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="America/New_York",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.NoteType"
    ) as mock_nt, patch(
        "scheduling_with_rooms.api.scheduling_api.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value=None,
    ):
        mock_nt.objects.filter.return_value.values.return_value.first.return_value = {
            "name": "Visit"
        }
        mock_appt.return_value.create.return_value = MagicMock(name="effect")
        result = h.book()
        # Returns: [json_response, *effects]
        assert len(result) >= 2


def test_book_zoned_start_time():
    h = _handler({
        "patient_id": "pt-1",
        "provider_id": "p1",
        "location_id": "loc-1",
        "note_type_id": "nt-1",
        "note_type_code": "VISIT",
        "start_time": "2026-05-07T10:00:00+00:00",
        "duration_minutes": 30,
    })
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.NoteType"
    ) as mock_nt, patch(
        "scheduling_with_rooms.api.scheduling_api.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value=None,
    ):
        mock_nt.objects.filter.return_value.values.return_value.first.return_value = {
            "name": "Visit"
        }
        mock_appt.return_value.create.return_value = MagicMock(name="effect")
        result = h.book()
        assert len(result) >= 2


def test_book_invalid_calendar_tz_propagates():
    """Local removed the try/except wrapper around ZoneInfo — an invalid
    calendar timezone now propagates to the caller instead of falling back
    to the naive start_time."""
    from zoneinfo import ZoneInfoNotFoundError

    h = _handler({
        "patient_id": "pt-1",
        "provider_id": "p1",
        "location_id": "loc-1",
        "note_type_id": "nt-1",
        "note_type_code": "VISIT",
        "start_time": "2026-05-07T10:00:00",
        "duration_minutes": 30,
    })
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="Bad/Zone",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.NoteType"
    ) as mock_nt, patch(
        "scheduling_with_rooms.api.scheduling_api.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value=None,
    ), pytest.raises(ZoneInfoNotFoundError):
        mock_nt.objects.filter.return_value.values.return_value.first.return_value = None
        mock_appt.return_value.create.return_value = MagicMock(name="effect")
        h.book()


def test_book_with_rfv_and_room_event_stashes_rr_event():
    """Local /book stashes the RR booking intent in cache (with the room
    NoteType id, duration, location, RR staff id, and description) instead
    of emitting a ScheduleEvent.create() effect. The APPOINTMENT_CREATED
    handler picks the stash up and creates the ScheduleEvent with
    parent_appointment_id set, so cancellation can cascade via the
    children relationship."""
    h = _handler({
        "patient_id": "pt-1",
        "provider_id": "p1",
        "location_id": "loc-1",
        "note_type_id": "nt-1",
        "note_type_code": "VISIT",
        "start_time": "2026-05-07T10:00:00+00:00",
        "duration_minutes": 30,
        "rr_staff_id": "room-1",
        "reason_for_visit": "fever",
    })
    nt_obj = MagicMock()
    nt_obj.id = "se-nt-1"
    nt_obj.code = "room"
    nt_obj.allow_custom_title = True

    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.NoteType"
    ) as mock_nt, patch(
        "scheduling_with_rooms.api.scheduling_api.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.api.scheduling_api.stash_rr_event"
    ) as mock_stash_rr, patch(
        "scheduling_with_rooms.api.scheduling_api.stash_rfv"
    ), patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value={"room-1"},
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.get_room_event_code_for",
        return_value="room",
    ):
        mock_nt.objects.filter.side_effect = [
            MagicMock(values=lambda *a: MagicMock(first=lambda: {"name": "Visit"})),
            MagicMock(first=lambda: nt_obj),
        ]
        mock_appt.return_value.create.return_value = MagicMock(name="appt-effect")
        result = h.book()

    # JSON response + appointment effect — no SE effect, since the SE is
    # created by the APPOINTMENT_CREATED handler from the stash.
    assert len(result) == 2
    mock_stash_rr.assert_called_once()
    kwargs = mock_stash_rr.call_args.kwargs
    assert kwargs["rr_staff_id"] == "room-1"
    assert kwargs["note_type_id"] == "se-nt-1"
    assert kwargs["duration_minutes"] == 30
    assert kwargs["location_id"] == "loc-1"
    # allow_custom_title=True → RFV mirrored into description.
    assert kwargs["description"] == "fever"


def test_book_room_event_skips_description_when_not_allowed():
    """When the room NoteType has allow_custom_title=False, the stash
    must carry an empty description (the RFV still lands on the patient
    note via the RFV command)."""
    h = _handler({
        "patient_id": "pt-1",
        "provider_id": "p1",
        "location_id": "loc-1",
        "note_type_id": "nt-1",
        "note_type_code": "VISIT",
        "start_time": "2026-05-07T10:00:00+00:00",
        "duration_minutes": 30,
        "rr_staff_id": "room-1",
        "reason_for_visit": "fever",
    })
    nt_obj = MagicMock()
    nt_obj.id = "se-nt-1"
    nt_obj.code = "room"
    nt_obj.allow_custom_title = False

    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.NoteType"
    ) as mock_nt, patch(
        "scheduling_with_rooms.api.scheduling_api.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.api.scheduling_api.stash_rr_event"
    ) as mock_stash_rr, patch(
        "scheduling_with_rooms.api.scheduling_api.stash_rfv"
    ), patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value={"room-1"},
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.get_room_event_code_for",
        return_value="room",
    ):
        mock_nt.objects.filter.side_effect = [
            MagicMock(values=lambda *a: MagicMock(first=lambda: None)),
            MagicMock(first=lambda: nt_obj),
        ]
        mock_appt.return_value.create.return_value = MagicMock(name="appt-effect")
        h.book()

    assert mock_stash_rr.call_args.kwargs["description"] == ""


def test_book_rr_room_no_event_code_skips():
    h = _handler({
        "patient_id": "pt-1",
        "provider_id": "p1",
        "location_id": "loc-1",
        "note_type_id": "nt-1",
        "note_type_code": "VISIT",
        "start_time": "2026-05-07T10:00:00+00:00",
        "duration_minutes": 30,
        "rr_staff_id": "room-1",
    })
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.NoteType"
    ) as mock_nt, patch(
        "scheduling_with_rooms.api.scheduling_api.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value={"room-1"},
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.get_room_event_code_for",
        return_value="",
    ):
        mock_nt.objects.filter.return_value.values.return_value.first.return_value = {
            "name": "Visit"
        }
        mock_appt.return_value.create.return_value = MagicMock(name="appt-effect")
        result = h.book()
        # No ScheduleEvent created.
        assert len(result) >= 2


def test_book_appointment_create_returns_list():
    h = _handler({
        "patient_id": "pt-1",
        "provider_id": "p1",
        "location_id": "loc-1",
        "note_type_id": "nt-1",
        "note_type_code": "VISIT",
        "start_time": "2026-05-07T10:00:00+00:00",
        "duration_minutes": 30,
    })
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.NoteType"
    ) as mock_nt, patch(
        "scheduling_with_rooms.api.scheduling_api.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value=None,
    ):
        mock_nt.objects.filter.return_value.values.return_value.first.return_value = None
        mock_appt.return_value.create.return_value = [
            MagicMock(name="e1"),
            MagicMock(name="e2"),
        ]
        result = h.book()
        # JSON response + 2 effects
        assert len(result) == 3


