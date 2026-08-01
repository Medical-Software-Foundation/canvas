"""Tests for api/scheduling_api.py."""

import datetime
import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from scheduling_with_rooms.api.scheduling_api import (
    SchedulingAPI,
    _allowed_room_keys_for,
)


def _json_body(response):
    """Decode a JSONResponse's body back into Python."""
    return json.loads(response.content)


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

def test_modal_empty_context_renders():
    h = _handler(query_params={})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.build_prefill",
        return_value={"mode": "schedule"},
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.render_to_string",
        return_value="<html>",
    ):
        result = h.modal()
        assert len(result) == 1


def test_modal_passes_prefill_to_template():
    h = _handler(query_params={"patient_id": "pt-1", "mode": "reschedule"})
    prefill = {"mode": "reschedule", "patient": {"id": "pt-1"}}
    with patch(
        "scheduling_with_rooms.api.scheduling_api.build_prefill",
        return_value=prefill,
    ) as mock_build, patch(
        "scheduling_with_rooms.api.scheduling_api.render_to_string",
        return_value="<html>",
    ) as mock_render:
        result = h.modal()

        assert len(result) == 1
        mock_build.assert_called_once_with(h.request.query_params)
        context = mock_render.call_args[0][1]
        assert context["prefill"] is prefill
        assert "theme_style" in context
        # Feeds the ?v= on the stylesheet link so a reinstall busts the cache.
        assert context["cache_bust"]


# /modal.css ------------------------------------------------------------

def test_modal_css_is_served_as_a_stylesheet():
    h = _handler()
    with patch(
        "scheduling_with_rooms.api.scheduling_api.render_to_string",
        return_value=":root { color: red; }",
    ) as mock_render:
        result = h.modal_css()

        assert len(result) == 1
        assert result[0].headers["Content-Type"] == "text/css"
        assert result[0].status_code == HTTPStatus.OK
        mock_render.assert_called_once_with("static/scheduling_modal.css")


def test_modal_css_contains_no_hardcoded_colors():
    """The stylesheet must consume theme tokens, or BRAND_* can't re-skin it."""
    import pathlib
    import re

    css = (
        pathlib.Path(__file__).parents[2]
        / "scheduling_with_rooms"
        / "static"
        / "scheduling_modal.css"
    ).read_text()
    hexes = re.findall(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", css)

    assert hexes == [], f"hardcoded colors leaked back in: {sorted(set(hexes))}"
    assert "var(--brand-primary)" in css


# /patients -------------------------------------------------------------

def test_patients_short_query_returns_400():
    h = _handler(query_params={"q": ""})
    result = h.patients()
    assert len(result) == 1


def _patient_search(mock_patient, first_name_rows, last_name_rows):
    """Patient.objects.filter().values()[:20] returns a list per search."""
    mock_patient.objects.filter.return_value.values.return_value.__getitem__.side_effect = [
        first_name_rows,
        last_name_rows,
    ]


def test_patients_dedupes_and_uses_last_known_timezone():
    h = _handler(query_params={"q": "bob"})
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
        "last_name": "Bob",  # matched on last name
        "birth_date": None,
        "last_known_timezone": None,
    }
    with patch("scheduling_with_rooms.api.scheduling_api.Patient") as mock_pt:
        _patient_search(mock_pt, [first_match, first_match], [last_match])

        body = _json_body(h.patients()[0])

        assert [p["id"] for p in body] == ["pt-1", "pt-2"]
        assert body[0]["full_name"] == "Bob Smith"
        assert body[0]["dob"] == "01/15/2000"
        assert body[0]["timezone"] == "America/New_York"
        # No setting row is consulted for search results.
        assert body[1]["timezone"] == ""
        assert body[1]["dob"] == ""


def test_patients_search_never_looks_up_preferred_timezone():
    """The per-patient lookup is deferred to /patient-timezone on selection."""
    h = _handler(query_params={"q": "bob"})
    row = {
        "id": "pt-1",
        "first_name": "Bob",
        "last_name": "Smith",
        "birth_date": None,
        "last_known_timezone": "",
    }
    with patch("scheduling_with_rooms.api.scheduling_api.Patient") as mock_pt, patch(
        "scheduling_with_rooms.api.scheduling_api.get_patient_timezone"
    ) as mock_tz:
        _patient_search(mock_pt, [row], [])

        h.patients()

        mock_tz.assert_not_called()


def test_patients_no_results_returns_empty_list():
    h = _handler(query_params={"q": "bob"})
    with patch("scheduling_with_rooms.api.scheduling_api.Patient") as mock_pt:
        _patient_search(mock_pt, [], [])

        assert _json_body(h.patients()[0]) == []


# /patient-timezone -----------------------------------------------------

def test_patient_timezone_missing_id_returns_400():
    h = _handler(query_params={"patient_id": ""})
    result = h.patient_timezone()
    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_patient_timezone_returns_preferred_setting():
    h = _handler(query_params={"patient_id": "pt-1"})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.get_patient_timezone",
        return_value="America/New_York",
    ) as mock_tz:
        result = h.patient_timezone()

        assert _json_body(result[0]) == {"timezone": "America/New_York"}
        mock_tz.assert_called_once_with("pt-1")


def test_patient_timezone_absent_setting_returns_empty_string():
    h = _handler(query_params={"patient_id": "pt-1"})
    with patch(
        "scheduling_with_rooms.api.scheduling_api.get_patient_timezone",
        return_value="",
    ):
        assert _json_body(h.patient_timezone()[0]) == {"timezone": ""}


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


# /all-slots — multi-location -------------------------------------------

def _multi_location_handler(**extra_params):
    params = {
        "location_ids": "loc-1,loc-2",
        "date": "2026-05-07",
        "duration": "30",
    }
    params.update(extra_params)
    return _handler(query_params=params)


def _patch_multi_location(rooms_required=False):
    """Patch everything _location_groups touches; returns the mock registry."""
    api = "scheduling_with_rooms.api.scheduling_api"
    patchers = {
        "PracticeLocation": patch(f"{api}.PracticeLocation"),
        "calendars": patch(f"{api}._fetch_clinic_calendars", return_value=["cal"]),
        "staff": patch(f"{api}._fetch_schedulable_staff", return_value=["staff"]),
        "providers_for": patch(f"{api}.get_providers_for_location"),
        "tz": patch(f"{api}.get_location_timezone", return_value="America/New_York"),
        "rooms_for": patch(
            f"{api}._allowed_room_keys_for",
            return_value={"r1"} if rooms_required else None,
        ),
        "room_staff": patch(f"{api}.resolve_room_staff", return_value=[]),
        "limits": patch(f"{api}.prefetch_concurrent_limits", return_value={}),
        "booked": patch(f"{api}.prefetch_blocking_appointments", return_value={}),
        "provider_slots": patch(f"{api}.build_all_provider_slots", return_value=[]),
        "room_slots": patch(f"{api}.build_all_room_slots", return_value=[]),
    }
    mocks = {name: p.start() for name, p in patchers.items()}
    mocks["PracticeLocation"].objects.filter.return_value.order_by.return_value.values.return_value = [
        {"id": "loc-1", "full_name": "Main"},
        {"id": "loc-2", "full_name": "Annex"},
    ]
    mocks["providers_for"].return_value = [{"id": "p1", "name": "Bob"}]
    return patchers, mocks


def test_all_slots_multi_location_returns_one_group_per_location():
    h = _multi_location_handler()
    patchers, mocks = _patch_multi_location()
    try:
        body = _json_body(h.all_slots()[0])

        assert [g["location_id"] for g in body["locations"]] == ["loc-1", "loc-2"]
        assert [g["location_name"] for g in body["locations"]] == ["Main", "Annex"]
        assert body["locations"][0]["timezone"] == "America/New_York"
    finally:
        for p in patchers.values():
            p.stop()


def test_all_slots_multi_location_shares_its_heavy_reads():
    """The point of the combined request: these run once, not once per location."""
    h = _multi_location_handler()
    patchers, mocks = _patch_multi_location()
    try:
        h.all_slots()

        mocks["calendars"].assert_called_once()
        mocks["staff"].assert_called_once()
        mocks["limits"].assert_called_once()
        # One appointment prefetch per distinct timezone — both locations agree.
        assert mocks["booked"].call_count == 1
    finally:
        for p in patchers.values():
            p.stop()


def test_all_slots_multi_location_prefetches_per_distinct_timezone():
    h = _multi_location_handler()
    patchers, mocks = _patch_multi_location()
    try:
        mocks["tz"].side_effect = ["America/New_York", "America/Denver"]

        h.all_slots()

        # Cached windows are timezone-converted, so they can't be shared across
        # locations in different zones.
        assert mocks["booked"].call_count == 2
    finally:
        for p in patchers.values():
            p.stop()


def test_all_slots_multi_location_skips_rooms_when_not_required():
    h = _multi_location_handler()
    patchers, mocks = _patch_multi_location(rooms_required=False)
    try:
        body = _json_body(h.all_slots()[0])

        mocks["room_slots"].assert_not_called()
        assert all(g["rooms"] == [] for g in body["locations"])
    finally:
        for p in patchers.values():
            p.stop()


def test_all_slots_multi_location_builds_rooms_per_location_when_required():
    h = _multi_location_handler()
    patchers, mocks = _patch_multi_location(rooms_required=True)
    try:
        h.all_slots()

        # Rooms are per-location columns, but resolved from one shared query.
        assert mocks["room_slots"].call_count == 2
        mocks["room_staff"].assert_called_once()
    finally:
        for p in patchers.values():
            p.stop()


def test_all_slots_multi_location_unknown_ids_return_no_groups():
    h = _multi_location_handler(location_ids="nope")
    patchers, mocks = _patch_multi_location()
    try:
        mocks["PracticeLocation"].objects.filter.return_value.order_by.return_value.values.return_value = []

        assert _json_body(h.all_slots()[0]) == {"locations": []}
    finally:
        for p in patchers.values():
            p.stop()


def test_all_slots_accepts_location_ids_in_place_of_location_id():
    """location_id is only required when location_ids isn't supplied."""
    h = _handler(query_params={"date": "2026-05-07", "duration": "30"})
    assert h.all_slots()[0].status_code == HTTPStatus.BAD_REQUEST

    h = _multi_location_handler()
    patchers, _ = _patch_multi_location()
    try:
        assert h.all_slots()[0].status_code == HTTPStatus.OK
    finally:
        for p in patchers.values():
            p.stop()


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
    NoteType id, duration, location, and RR staff id) instead
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
    # No description is stashed — rr_event_origination never consumed it, and
    # room ScheduleEvents deliberately carry none.
    assert "description" not in kwargs


def test_book_room_event_stash_never_carries_a_description():
    """No path sets a room ScheduleEvent description.

    The SDK validates `description` against allow_custom_title by re-resolving
    note_type_id — and NoteType.id is not unique on real instances, so that
    lookup can hit a different row than the one we checked. Sending none avoids
    the whole class of failure; the reason for visit lives on the patient note.
    """
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
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.find_room_events", return_value=[]
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.record_room", return_value=[]
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


# /book — reschedule ----------------------------------------------------

def _reschedule_body(**overrides):
    body = {
        "patient_id": "pt-1",
        "provider_id": "p1",
        "location_id": "loc-1",
        "note_type_id": "nt-1",
        "note_type_code": "VISIT",
        "start_time": "2026-05-07T10:00:00+00:00",
        "duration_minutes": 45,
        "appointment_id": "appt-1",
    }
    body.update(overrides)
    return body


def test_book_with_appointment_id_updates_instead_of_creating():
    h = _handler(_reschedule_body())
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.NoteType"
    ) as mock_nt, patch(
        "scheduling_with_rooms.api.scheduling_api.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.api.scheduling_api.stash_rfv"
    ) as mock_stash, patch.object(
        h.__class__, "_reschedule_room_events", return_value=[]
    ) as mock_rooms:
        mock_nt.objects.filter.return_value.values.return_value.first.return_value = None
        mock_appt.return_value.reschedule.return_value = MagicMock(name="reschedule-effect")

        result = h.book()

        # The existing appointment is moved; nothing new is booked.
        mock_appt.return_value.reschedule.assert_called_once()
        mock_appt.return_value.create.assert_not_called()
        assert mock_appt.call_args.kwargs["instance_id"] == "appt-1"
        assert mock_appt.call_args.kwargs["duration_minutes"] == 45
        # The note already exists, so the RFV stash doesn't apply.
        mock_stash.assert_not_called()
        mock_rooms.assert_called_once()
        assert len(result) == 2


def test_book_reschedule_writes_rfv_inline_instead_of_stashing():
    """APPOINTMENT_CREATED doesn't fire for a move, so the cache handoff is out."""
    h = _handler(_reschedule_body(reason_for_visit="Follow up on labs"))
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.NoteType"
    ) as mock_nt, patch(
        "scheduling_with_rooms.api.scheduling_api.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.api.scheduling_api.stash_rfv"
    ) as mock_stash, patch(
        "scheduling_with_rooms.api.scheduling_api.stash_rr_event"
    ) as mock_stash_rr, patch.object(
        h.__class__, "_reschedule_room_events", return_value=[]
    ), patch.object(
        h.__class__, "_reason_for_visit_effects", return_value=[]
    ) as mock_rfv:
        mock_nt.objects.filter.return_value.values.return_value.first.return_value = None
        mock_appt.return_value.reschedule.return_value = MagicMock(name="reschedule-effect")

        h.book()

        mock_stash.assert_not_called()
        mock_stash_rr.assert_not_called()
        mock_rfv.assert_called_once_with("appt-1", "Follow up on labs")


def test_book_reschedule_includes_room_effects():
    h = _handler(_reschedule_body(rr_staff_id="rr-1"))
    room_effects = [MagicMock(name="delete"), MagicMock(name="create")]
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.NoteType"
    ) as mock_nt, patch(
        "scheduling_with_rooms.api.scheduling_api.Appointment"
    ) as mock_appt, patch.object(
        h.__class__, "_reschedule_room_events", return_value=room_effects
    ):
        mock_nt.objects.filter.return_value.values.return_value.first.return_value = None
        mock_appt.return_value.reschedule.return_value = MagicMock(name="reschedule-effect")

        result = h.book()

        # JSON response + appointment update + both room effects.
        assert len(result) == 4


# _reason_for_visit_effects ---------------------------------------------

def _appointment_with_note(note_id="note-1"):
    appointment = MagicMock()
    appointment.note = MagicMock()
    appointment.note.id = note_id
    return appointment


def _patch_rfv(appointment, existing):
    """Patch the appointment lookup and the existing-RFV-command lookup."""
    model = patch("scheduling_with_rooms.api.scheduling_api.AppointmentModel")
    command = patch("scheduling_with_rooms.api.scheduling_api.Command")
    cmd_cls = patch("scheduling_with_rooms.api.scheduling_api.ReasonForVisitCommand")
    mock_model, mock_command, mock_cls = model.start(), command.start(), cmd_cls.start()
    mock_model.objects.select_related.return_value.filter.return_value.first.return_value = (
        appointment
    )
    mock_command.objects.filter.return_value.order_by.return_value.values.return_value.first.return_value = (
        existing
    )
    return (model, command, cmd_cls), mock_command, mock_cls


def test_rfv_effects_empty_text_is_a_no_op():
    h = _handler()
    with patch("scheduling_with_rooms.api.scheduling_api.AppointmentModel") as mock_model:
        assert h._reason_for_visit_effects("appt-1", "") == []
        mock_model.objects.select_related.assert_not_called()


def test_rfv_effects_originates_when_note_has_none():
    h = _handler()
    patches, mock_command, mock_cls = _patch_rfv(_appointment_with_note(), None)
    try:
        mock_cls.return_value.originate.return_value = MagicMock(name="originate")

        effects = h._reason_for_visit_effects("appt-1", "Follow up on labs")

        assert len(effects) == 1
        mock_cls.return_value.originate.assert_called_once()
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["note_uuid"] == "note-1"
        assert kwargs["comment"] == "Follow up on labs"
        # Only staged commands count — an RFV is never committed.
        assert mock_command.objects.filter.call_args.kwargs["state"] == "staged"
    finally:
        for p in patches:
            p.stop()


def test_rfv_effects_edits_when_text_changed():
    h = _handler()
    existing = {"id": "cmd-1", "data": {"comment": "Old reason"}}
    patches, _, mock_cls = _patch_rfv(_appointment_with_note(), existing)
    try:
        mock_cls.return_value.edit.return_value = MagicMock(name="edit")

        effects = h._reason_for_visit_effects("appt-1", "New reason")

        assert len(effects) == 1
        mock_cls.return_value.edit.assert_called_once()
        mock_cls.return_value.originate.assert_not_called()
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["command_uuid"] == "cmd-1"
        assert kwargs["comment"] == "New reason"
    finally:
        for p in patches:
            p.stop()


def test_rfv_effects_unchanged_text_emits_nothing():
    h = _handler()
    existing = {"id": "cmd-1", "data": {"comment": "Same reason"}}
    patches, _, mock_cls = _patch_rfv(_appointment_with_note(), existing)
    try:
        assert h._reason_for_visit_effects("appt-1", "Same reason") == []
        mock_cls.return_value.edit.assert_not_called()
        mock_cls.return_value.originate.assert_not_called()
    finally:
        for p in patches:
            p.stop()


def test_rfv_effects_treats_null_data_as_absent_comment():
    h = _handler()
    patches, _, mock_cls = _patch_rfv(_appointment_with_note(), {"id": "cmd-1", "data": None})
    try:
        mock_cls.return_value.edit.return_value = MagicMock(name="edit")

        effects = h._reason_for_visit_effects("appt-1", "A reason")

        assert len(effects) == 1
        mock_cls.return_value.edit.assert_called_once()
    finally:
        for p in patches:
            p.stop()


def test_rfv_effects_appointment_without_note_emits_nothing():
    h = _handler()
    appointment = MagicMock()
    appointment.note = None
    patches, _, mock_cls = _patch_rfv(appointment, None)
    try:
        assert h._reason_for_visit_effects("appt-1", "A reason") == []
        mock_cls.return_value.originate.assert_not_called()
    finally:
        for p in patches:
            p.stop()


def test_rfv_effects_missing_appointment_emits_nothing():
    h = _handler()
    patches, _, mock_cls = _patch_rfv(None, None)
    try:
        assert h._reason_for_visit_effects("appt-1", "A reason") == []
        mock_cls.return_value.originate.assert_not_called()
    finally:
        for p in patches:
            p.stop()


# _reschedule_room_events --------------------------------------------------

def _room_child(status="unconfirmed", category="schedule_event"):
    child = MagicMock()
    child.id = "child-1"
    child.status = status
    child.note_type.category = category
    return child


def _reschedule_room_events_kwargs(**overrides):
    kwargs = {
        "appointment_id": "appt-1",
        "rr_staff_id": "rr-1",
        "note_type_code": "VISIT",
        "start_time": datetime.datetime(2026, 5, 7, 14, 0, tzinfo=datetime.timezone.utc),
        "duration_minutes": 45,
        "location_id": "loc-1",
        "patient_id": "pt-1",
    }
    kwargs.update(overrides)
    return kwargs


def test_reschedule_room_events_missing_appointment_returns_empty():
    h = _handler()
    with patch(
        "scheduling_with_rooms.api.scheduling_api.AppointmentModel"
    ) as mock_model:
        mock_model.objects.select_related.return_value.prefetch_related.return_value.filter.return_value.first.return_value = None
        assert h._reschedule_room_events(**_reschedule_room_events_kwargs()) == []


def _room_env(appointment, room_required=True, existing=None):
    """Patch everything _reschedule_room_events touches.

    `existing` is what the shared find_room_events lookup returns; it has its
    own coverage in test_room_link.py.
    """
    api = "scheduling_with_rooms.api.scheduling_api"
    patchers = [
        patch(f"{api}.AppointmentModel"),
        patch(f"{api}.ScheduleEvent"),
        patch(f"{api}._allowed_room_keys_for", return_value={"rr-1"} if room_required else None),
        patch(f"{api}.get_room_event_code_for", return_value="ROOM"),
        patch(f"{api}.NoteType"),
        patch(f"{api}.record_room", return_value=[]),
        patch(f"{api}.find_room_events", return_value=list(existing or [])),
    ]
    mock_model, mock_event, _keys, _code, mock_nt, _rec, _find = [
        p.start() for p in patchers
    ]
    mock_model.objects.select_related.return_value.prefetch_related.return_value.filter.return_value.first.return_value = (
        appointment
    )
    room_nt = MagicMock()
    room_nt.id = "room-nt"
    mock_nt.objects.filter.return_value.first.return_value = room_nt
    return patchers, mock_event


def test_reschedule_room_events_moves_the_existing_event():
    """One reschedule, not a delete plus a create.

    Keeps the event history and the parent_appointment_id link, and sets no
    note_type_id so the SDK never re-resolves it (which is what broke on
    instances where NoteType.id is shared across rows).
    """
    h = _handler()
    appointment = MagicMock()
    patchers, mock_event = _room_env(appointment, existing=[_room_child()])
    try:
        effects = h._reschedule_room_events(**_reschedule_room_events_kwargs())

        assert len(effects) == 1
        mock_event.return_value.reschedule.assert_called_once()
        mock_event.return_value.create.assert_not_called()
        mock_event.return_value.delete.assert_not_called()

        kwargs = mock_event.call_args.kwargs
        assert kwargs["instance_id"] == "child-1"
        # A room change rides along on the same call.
        assert kwargs["provider_id"] == "rr-1"
        assert "note_type_id" not in kwargs
        assert "description" not in kwargs
    finally:
        for p in patchers:
            p.stop()


def test_reschedule_room_events_creates_one_when_none_exists():
    """The appointment predates rooms being required for its visit type."""
    h = _handler()
    appointment = MagicMock()
    patchers, mock_event = _room_env(appointment, existing=[])
    try:
        effects = h._reschedule_room_events(**_reschedule_room_events_kwargs())

        assert len(effects) == 1
        mock_event.return_value.create.assert_called_once()
        kwargs = mock_event.call_args.kwargs
        assert kwargs["parent_appointment_id"] == "appt-1"
        assert kwargs["provider_id"] == "rr-1"
        assert "description" not in kwargs
    finally:
        for p in patchers:
            p.stop()


def test_reschedule_room_events_deletes_extra_duplicates():
    h = _handler()
    second = _room_child()
    second.id = "child-2"
    appointment = MagicMock()
    patchers, mock_event = _room_env(appointment, existing=[_room_child(), second])
    try:
        effects = h._reschedule_room_events(**_reschedule_room_events_kwargs())

        # One reschedule for the primary, one delete for the duplicate.
        assert len(effects) == 2
        mock_event.return_value.reschedule.assert_called_once()
        mock_event.return_value.delete.assert_called_once()
    finally:
        for p in patchers:
            p.stop()


def test_reschedule_room_events_skips_non_schedule_event_children():
    h = _handler()
    appointment = MagicMock()
    appointment.children.all.return_value = [_room_child(category="encounter")]
    with patch(
        "scheduling_with_rooms.api.scheduling_api.AppointmentModel"
    ) as mock_model, patch(
        "scheduling_with_rooms.api.scheduling_api.ScheduleEvent"
    ) as mock_event, patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value=None,
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.find_room_events", return_value=[]
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.record_room", return_value=[]
    ):
        mock_model.objects.select_related.return_value.prefetch_related.return_value.filter.return_value.first.return_value = (
            appointment
        )

        assert h._reschedule_room_events(**_reschedule_room_events_kwargs()) == []
        mock_event.return_value.delete.assert_not_called()


def test_reschedule_room_events_without_room_only_deletes():
    """Switching to a room-free visit type on reschedule strips the old room."""
    h = _handler()
    appointment = MagicMock()
    patchers, mock_event = _room_env(
        appointment, room_required=False, existing=[_room_child()]
    )
    try:
        mock_event.return_value.delete.return_value = MagicMock(name="delete-effect")

        effects = h._reschedule_room_events(
            **_reschedule_room_events_kwargs(rr_staff_id="")
        )

        assert len(effects) == 1
        mock_event.return_value.delete.assert_called_once()
        mock_event.return_value.create.assert_not_called()
        mock_event.return_value.reschedule.assert_not_called()
    finally:
        for p in patchers:
            p.stop()


def test_reschedule_room_events_missing_room_note_type_skips_create():
    h = _handler()
    appointment = MagicMock()
    appointment.children.all.return_value = []
    with patch(
        "scheduling_with_rooms.api.scheduling_api.AppointmentModel"
    ) as mock_model, patch(
        "scheduling_with_rooms.api.scheduling_api.ScheduleEvent"
    ) as mock_event, patch(
        "scheduling_with_rooms.api.scheduling_api._allowed_room_keys_for",
        return_value={"rr-1"},
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.get_room_event_code_for",
        return_value="",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.find_room_events", return_value=[]
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.record_room", return_value=[]
    ):
        mock_model.objects.select_related.return_value.prefetch_related.return_value.filter.return_value.first.return_value = (
            appointment
        )

        assert h._reschedule_room_events(**_reschedule_room_events_kwargs()) == []
        mock_event.return_value.create.assert_not_called()


# NoteType versioning ---------------------------------------------------

def test_book_resolves_the_active_note_type_version():
    """Note types are version-controlled: many rows share an id, one is active.

    Without is_active, .first() returns an arbitrary version — and a renamed
    note type would default the reason for visit to its old name.
    """
    h = _handler(_reschedule_body())
    with patch.object(h.__class__, "_location_name", return_value="Office"), patch(
        "scheduling_with_rooms.api.scheduling_api.get_location_timezone",
        return_value="UTC",
    ), patch(
        "scheduling_with_rooms.api.scheduling_api.NoteType"
    ) as mock_nt, patch(
        "scheduling_with_rooms.api.scheduling_api.Appointment"
    ) as mock_appt, patch.object(
        h.__class__, "_reschedule_room_events", return_value=[]
    ), patch.object(
        h.__class__, "_reason_for_visit_effects", return_value=[]
    ):
        mock_nt.objects.filter.return_value.values.return_value.first.return_value = None
        mock_appt.return_value.reschedule.return_value = MagicMock(name="effect")

        h.book()

        assert mock_nt.objects.filter.call_args.kwargs["is_active"] is True
