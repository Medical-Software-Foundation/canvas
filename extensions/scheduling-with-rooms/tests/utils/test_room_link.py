"""Tests for utils/room_link.py."""

from unittest.mock import MagicMock, patch

from scheduling_with_rooms.utils.room_link import (
    ROOM_STAFF_KEY,
    find_room_events,
    record_room,
    room_staff_key_for_note,
)

MODULE = "scheduling_with_rooms.utils.room_link"


def test_key_is_namespaced_to_this_plugin():
    """Note metadata is shared, so the key must not be able to collide."""
    assert ROOM_STAFF_KEY.startswith("scheduling_with_rooms:")


# record_room -----------------------------------------------------------

def test_record_room_upserts_metadata_on_the_note():
    with patch(f"{MODULE}.Note") as mock_note:
        mock_note.return_value.upsert_metadata.return_value = MagicMock(name="effect")

        effects = record_room("note-1", "rr-1")

        assert len(effects) == 1
        assert mock_note.call_args.kwargs["instance_id"] == "note-1"
        mock_note.return_value.upsert_metadata.assert_called_once_with(
            ROOM_STAFF_KEY, "rr-1"
        )


def test_record_room_is_a_no_op_without_a_note_or_room():
    with patch(f"{MODULE}.Note") as mock_note:
        assert record_room("", "rr-1") == []
        assert record_room("note-1", "") == []
        mock_note.assert_not_called()


# room_staff_key_for_note -----------------------------------------------

def _metadata(value):
    patcher = patch(f"{MODULE}.NoteMetadata")
    mock = patcher.start()
    mock.objects.filter.return_value.values.return_value.first.return_value = (
        {"value": value} if value is not None else None
    )
    return patcher, mock


def test_reads_the_recorded_room():
    patcher, mock = _metadata("rr-1")
    try:
        assert room_staff_key_for_note("note-1") == "rr-1"

        kwargs = mock.objects.filter.call_args.kwargs
        assert kwargs["note__id"] == "note-1"
        assert kwargs["key"] == ROOM_STAFF_KEY
    finally:
        patcher.stop()


def test_missing_metadata_returns_empty_string():
    patcher, _ = _metadata(None)
    try:
        assert room_staff_key_for_note("note-1") == ""
    finally:
        patcher.stop()


def test_blank_value_returns_empty_string():
    patcher, _ = _metadata("   ")
    try:
        assert room_staff_key_for_note("note-1") == ""
    finally:
        patcher.stop()


def test_no_note_skips_the_query():
    patcher, mock = _metadata("rr-1")
    try:
        assert room_staff_key_for_note("") == ""
        mock.objects.filter.assert_not_called()
    finally:
        patcher.stop()


# find_room_events ------------------------------------------------------

def _child(category="schedule_event", status="unconfirmed", note_type=...):
    child = MagicMock()
    child.id = "child-1"
    child.status = status
    if note_type is None:
        child.note_type = None
    elif note_type is ...:
        nt = MagicMock()
        nt.category = category
        child.note_type = nt
    else:
        child.note_type = note_type
    return child


def _appointment(children=(), note_id="note-1", patient_id="pt-1"):
    import datetime

    appointment = MagicMock()
    appointment.children.all.return_value = list(children)
    appointment.note.id = note_id
    appointment.patient.id = patient_id
    appointment.start_time = datetime.datetime(
        2026, 8, 4, 13, 0, tzinfo=datetime.timezone.utc
    )
    return appointment


def test_find_prefers_the_parent_link():
    """Never-rescheduled appointments still have working children."""
    child = _child()
    with patch(f"{MODULE}.NoteMetadata") as mock_meta:
        assert find_room_events(_appointment(children=[child])) == [child]
        # No need to consult the note.
        mock_meta.objects.filter.assert_not_called()


def test_find_skips_children_that_are_not_room_events():
    """Encounter-typed or detached children aren't rooms."""
    for child in (_child(category="encounter"), _child(note_type=None)):
        with patch(f"{MODULE}.NoteMetadata") as mock_meta:
            mock_meta.objects.filter.return_value.values.return_value.first.return_value = None
            assert find_room_events(_appointment(children=[child])) == []


def test_find_skips_cancelled_children():
    with patch(f"{MODULE}.NoteMetadata") as mock_meta:
        mock_meta.objects.filter.return_value.values.return_value.first.return_value = None
        assert find_room_events(_appointment(children=[_child(status="cancelled")])) == []


def test_find_recovers_orphan_via_the_note():
    """The case reschedule creates: parent_appointment_id is null."""
    orphan = MagicMock()
    with patch(f"{MODULE}.NoteMetadata") as mock_meta, patch(
        f"{MODULE}.Appointment"
    ) as mock_appt:
        mock_meta.objects.filter.return_value.values.return_value.first.return_value = {
            "value": "rr-1"
        }
        mock_appt.objects.filter.return_value.exclude.return_value = [orphan]

        appointment = _appointment(children=[])
        assert find_room_events(appointment) == [orphan]

        kwargs = mock_appt.objects.filter.call_args.kwargs
        assert kwargs["patient__id"] == "pt-1"
        assert kwargs["provider__id"] == "rr-1"
        assert kwargs["start_time"] == appointment.start_time
        assert kwargs["note_type__category"] == "schedule_event"


def test_find_returns_empty_when_the_note_records_no_room():
    with patch(f"{MODULE}.NoteMetadata") as mock_meta, patch(
        f"{MODULE}.Appointment"
    ) as mock_appt:
        mock_meta.objects.filter.return_value.values.return_value.first.return_value = None

        assert find_room_events(_appointment(children=[])) == []
        mock_appt.objects.filter.assert_not_called()


def test_find_returns_empty_without_a_patient():
    with patch(f"{MODULE}.NoteMetadata") as mock_meta, patch(
        f"{MODULE}.Appointment"
    ) as mock_appt:
        mock_meta.objects.filter.return_value.values.return_value.first.return_value = {
            "value": "rr-1"
        }
        appointment = _appointment(children=[])
        appointment.patient = None

        assert find_room_events(appointment) == []
        mock_appt.objects.filter.assert_not_called()
