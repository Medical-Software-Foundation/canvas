"""Tests for group_therapy.services.sessions group-session discovery."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from group_therapy.services.sessions import (
    _documented_note_dbids,
    _group_note_codes,
    _normalize,
    _note_states_by_dbid,
    _patient_photos,
    find_group_sessions,
)


def test_normalize_matches_code_and_display_forms():
    assert _normalize("Group_Therapy") == _normalize("Group Therapy") == "grouptherapy"


def _row(provider_id, start, patient_id, first, last, note_dbid, note_uuid, bd=None):
    return {
        "start_time": start,
        "provider__id": provider_id,
        "provider__first_name": "Dana",
        "provider__last_name": "Wang",
        "patient__id": patient_id,
        "patient__first_name": first,
        "patient__last_name": last,
        "patient__birth_date": bd,
        "note_id": note_dbid,
        "note__id": note_uuid,
    }


def _patches(func):
    func = patch("group_therapy.services.sessions._appointment_rows")(func)
    func = patch("group_therapy.services.sessions._group_note_codes")(func)
    func = patch("group_therapy.services.sessions._note_states_by_dbid")(func)
    func = patch("group_therapy.services.sessions._documented_note_dbids")(func)
    func = patch("group_therapy.services.sessions._patient_photos", return_value={})(func)
    return func


@_patches
def test_session_classifies_states_documented_and_codes(mock_rows, mock_codes, mock_states, mock_documented, mock_photos):
    t10 = datetime(2026, 6, 27, 10, 0)
    rows = [
        _row("prov1", t10, "pA", "Amy", "Adams", 1, "uA", date(1990, 1, 2)),
        _row("prov1", t10, "pB", "Bob", "Boyd", 2, "uB"),
    ]
    mock_rows.return_value = rows
    mock_codes.return_value = {1: "Group_Therapy", 2: "Group_Therapy"}
    mock_states.return_value = {1: "BKD", 2: "CVD"}
    mock_documented.return_value = {2}

    session = find_group_sessions(date(2026, 6, 27), ["Group_Therapy"])[0]
    assert session["rfv_codes"] == ["Group_Therapy"]
    roster = session["roster"]
    amy = next(r for r in roster if r["name"] == "Amy Adams")
    bob = next(r for r in roster if r["name"] == "Bob Boyd")
    assert amy["needs_checkin"] is True and amy["blocked"] is False and amy["documented"] is False
    assert amy["note_id"] == "uA" and amy["note_state"] == "BKD" and amy["photo_url"] == ""
    assert amy["noshow"] is False
    assert bob["needs_checkin"] is False and bob["documented"] is True


@_patches
def test_session_captures_matched_rfv_codes(mock_rows, mock_codes, mock_states, mock_documented, mock_photos):
    """The matched RFV code(s) drive template resolution downstream."""
    t10 = datetime(2026, 6, 27, 10, 0)
    mock_rows.return_value = [
        _row("prov1", t10, "pA", "Amy", "Adams", 1, "uA"),
        _row("prov1", t10, "pB", "Bob", "Boyd", 2, "uB"),
    ]
    mock_codes.return_value = {1: "GROUP_SCREENING", 2: "GROUP_SCREENING"}
    mock_states.return_value = {1: "CVD", 2: "CVD"}
    mock_documented.return_value = set()
    session = find_group_sessions(date(2026, 6, 27), ["Group_Therapy", "GROUP_SCREENING"])[0]
    assert session["rfv_codes"] == ["GROUP_SCREENING"]


@_patches
def test_noshow_flagged(mock_rows, mock_codes, mock_states, mock_documented, mock_photos):
    t10 = datetime(2026, 6, 27, 10, 0)
    mock_rows.return_value = [
        _row("prov1", t10, "pA", "Amy", "Adams", 1, "uA"),
        _row("prov1", t10, "pB", "Bob", "Boyd", 2, "uB"),
    ]
    mock_codes.return_value = {1: "Group_Therapy", 2: "Group_Therapy"}
    mock_states.return_value = {1: "NSW", 2: "CVD"}
    mock_documented.return_value = set()
    roster = find_group_sessions(date(2026, 6, 27), ["Group_Therapy"])[0]["roster"]
    amy = next(r for r in roster if r["name"] == "Amy Adams")
    assert amy["noshow"] is True and amy["blocked"] is True  # no-show is not documentable...
    bob = next(r for r in roster if r["name"] == "Bob Boyd")
    assert bob["noshow"] is False


@_patches
def test_locked_note_is_blocked(mock_rows, mock_codes, mock_states, mock_documented, mock_photos):
    t10 = datetime(2026, 6, 27, 10, 0)
    mock_rows.return_value = [
        _row("prov1", t10, "pA", "Amy", "Adams", 1, "uA"),
        _row("prov1", t10, "pB", "Bob", "Boyd", 2, "uB"),
    ]
    mock_codes.return_value = {1: "Group_Therapy", 2: "Group_Therapy"}
    mock_states.return_value = {1: "LKD", 2: "SGN"}
    mock_documented.return_value = set()
    roster = find_group_sessions(date(2026, 6, 27), ["Group_Therapy"])[0]["roster"]
    assert all(r["blocked"] and not r["noshow"] for r in roster)


@_patches
def test_singleton_slot_excluded(mock_rows, mock_codes, mock_states, mock_documented, mock_photos):
    t10 = datetime(2026, 6, 27, 10, 0)
    mock_rows.return_value = [_row("prov1", t10, "pA", "Amy", "Adams", 1, "uA")]
    mock_codes.return_value = {1: "Group_Therapy"}
    mock_states.return_value = {1: "BKD"}
    mock_documented.return_value = set()
    assert find_group_sessions(date(2026, 6, 27), ["Group_Therapy"]) == []


@_patches
def test_non_group_rfv_excluded(mock_rows, mock_codes, mock_states, mock_documented, mock_photos):
    t10 = datetime(2026, 6, 27, 10, 0)
    mock_rows.return_value = [
        _row("prov1", t10, "pA", "Amy", "Adams", 1, "uA"),
        _row("prov1", t10, "pB", "Bob", "Boyd", 2, "uB"),
    ]
    mock_codes.return_value = {}
    mock_states.return_value = {}
    mock_documented.return_value = set()
    assert find_group_sessions(date(2026, 6, 27), ["Group_Therapy"]) == []


@_patches
def test_two_providers_two_sessions(mock_rows, mock_codes, mock_states, mock_documented, mock_photos):
    t10, t11 = datetime(2026, 6, 27, 10, 0), datetime(2026, 6, 27, 11, 0)
    mock_rows.return_value = [
        _row("prov1", t10, "pA", "Amy", "Adams", 1, "uA"),
        _row("prov1", t10, "pB", "Bob", "Boyd", 2, "uB"),
        _row("prov2", t11, "pC", "Cara", "Cole", 3, "uC"),
        _row("prov2", t11, "pD", "Dan", "Diaz", 4, "uD"),
    ]
    mock_codes.return_value = {1: "Group_Therapy", 2: "Group_Therapy", 3: "Group_Therapy", 4: "Group_Therapy"}
    mock_states.return_value = {1: "BKD", 2: "BKD", 3: "CVD", 4: "CVD"}
    mock_documented.return_value = set()
    sessions = find_group_sessions(date(2026, 6, 27), ["Group_Therapy"])
    assert [s["start_time"] for s in sessions] == [t10.isoformat(), t11.isoformat()]


@patch("group_therapy.services.sessions._appointment_rows")
def test_query_error_degrades_to_empty(mock_rows):
    mock_rows.side_effect = AttributeError("boom")
    assert find_group_sessions(date(2026, 6, 27), ["Group_Therapy"]) == []


def _cmd(note_dbid, coding=None):
    cmd = MagicMock()
    cmd.note_id = note_dbid
    cmd.data = {"coding": coding} if coding is not None else {}
    return cmd


@patch("group_therapy.services.sessions.Command")
def test_group_note_codes_maps_dbid_to_matched_code(mock_command):
    mock_command.objects.filter.return_value = [
        _cmd(1, {"value": "165002", "text": "Group Therapy"}),
        _cmd(2, {"value": "GROUP_SCREENING", "text": "Group Screening"}),
        _cmd(3, {"value": "MED_MANAGEMENT_NEW", "text": "Medication Management - New"}),
    ]
    result = _group_note_codes([1, 2, 3], ["Group_Therapy", "GROUP_SCREENING"])
    assert result == {1: "Group_Therapy", 2: "GROUP_SCREENING"}


def test_group_note_codes_empty_skips_query():
    assert _group_note_codes([], ["Group_Therapy"]) == {}


@patch("group_therapy.services.sessions.Command")
def test_documented_note_dbids(mock_command):
    qs = MagicMock()
    qs.values_list.return_value = [3, 4]
    mock_command.objects.filter.return_value = qs
    assert _documented_note_dbids([3, 4, 5]) == {3, 4}
    assert mock_command.objects.filter.call_args.kwargs["schema_key__startswith"] == "groupTherapyNote"


def test_documented_note_dbids_empty_skips_query():
    assert _documented_note_dbids([]) == set()


@patch("group_therapy.services.sessions.CurrentNoteStateEvent")
def test_note_states_by_dbid(mock_cnse):
    mock_cnse.objects.filter.return_value.values_list.return_value = [(1, "BKD"), (2, "CVD")]
    assert _note_states_by_dbid([1, 2]) == {1: "BKD", 2: "CVD"}


def test_note_states_by_dbid_empty_skips_query():
    assert _note_states_by_dbid([]) == {}


@patch("group_therapy.services.sessions.Patient")
def test_patient_photos_returns_presigned_for_real_photos(mock_patient):
    p1 = MagicMock(); p1.id = "u1"; p1.photo = MagicMock(); p1.photo_url = "https://signed/u1"
    p2 = MagicMock(); p2.id = "u2"; p2.photo = None
    mock_patient.objects.filter.return_value = [p1, p2]
    assert _patient_photos(["u1", "u2"]) == {"u1": "https://signed/u1"}


def test_patient_photos_empty_skips_query():
    assert _patient_photos([]) == {}


@patch("group_therapy.services.sessions.Patient")
def test_patient_photos_degrades_on_error(mock_patient):
    mock_patient.objects.filter.side_effect = AttributeError("no photo_url in this SDK")
    assert _patient_photos(["u1"]) == {}


@patch("group_therapy.services.sessions.Appointment")
def test_appointment_rows_queries_live_appointments(mock_appt):
    from group_therapy.services.sessions import _appointment_rows
    chain = mock_appt.objects.filter.return_value.exclude.return_value.filter.return_value
    chain.values.return_value = [{"patient_id": "p1"}]
    rows = _appointment_rows(date(2026, 6, 27))
    assert rows == [{"patient_id": "p1"}]
    mock_appt.objects.filter.assert_called_once()
