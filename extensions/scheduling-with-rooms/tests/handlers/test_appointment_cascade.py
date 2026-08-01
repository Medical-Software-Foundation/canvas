"""Tests for handlers/appointment_cascade.py.

The cascade releases the room when a patient appointment is cancelled. *Which*
event that is comes from ``room_link.find_room_events`` — children first, then
the room recorded on the note, since ``ScheduleEvent.reschedule()`` nulls
``parent_appointment_id``. That lookup is covered in
tests/utils/test_room_link.py and stubbed here, so these tests are about what
the handler does with the result.

No reschedule guard is needed: Canvas emits APPOINTMENT_UPDATED, not
APPOINTMENT_CANCELED, for an appointment a reschedule supersedes (verified
against bigleaphealth-dev logs).
"""

from unittest.mock import MagicMock, patch

from scheduling_with_rooms.handlers.appointment_cascade import (
    AppointmentCascadeHandler,
)

MODULE = "scheduling_with_rooms.handlers.appointment_cascade"


def _handler(appt_id: str = "appt-1") -> AppointmentCascadeHandler:
    h = AppointmentCascadeHandler.__new__(AppointmentCascadeHandler)
    event = MagicMock()
    event.target.id = appt_id
    h.event = event
    h.secrets = {}
    return h


def _room_event(event_id: str) -> MagicMock:
    event = MagicMock()
    event.id = event_id
    return event


def _env(appointment, room_events=(), missing=False):
    """Patch the appointment load and the shared room lookup."""
    appt_patcher = patch(f"{MODULE}.Appointment")
    find_patcher = patch(f"{MODULE}.find_room_events", return_value=list(room_events))
    event_patcher = patch(f"{MODULE}.ScheduleEvent")
    mock_appt, mock_find, mock_event = (
        appt_patcher.start(),
        find_patcher.start(),
        event_patcher.start(),
    )
    chain = mock_appt.objects.select_related.return_value.prefetch_related.return_value
    if missing:
        from canvas_sdk.v1.data.appointment import Appointment as Appt

        mock_appt.DoesNotExist = Appt.DoesNotExist
        chain.get.side_effect = Appt.DoesNotExist
    else:
        chain.get.return_value = appointment
    return (appt_patcher, find_patcher, event_patcher), mock_find, mock_event


def test_appointment_not_found_returns_empty():
    h = _handler()
    patchers, _, mock_event = _env(None, missing=True)
    try:
        assert h.compute() == []
        mock_event.return_value.delete.assert_not_called()
    finally:
        for p in patchers:
            p.stop()


def test_no_room_event_returns_empty():
    h = _handler()
    patchers, _, mock_event = _env(MagicMock(), room_events=[])
    try:
        assert h.compute() == []
        mock_event.return_value.delete.assert_not_called()
    finally:
        for p in patchers:
            p.stop()


def test_deletes_the_room_event():
    h = _handler()
    patchers, _, mock_event = _env(MagicMock(), room_events=[_room_event("room-ev-1")])
    try:
        mock_event.return_value.delete.return_value = MagicMock(name="delete-effect")

        effects = h.compute()

        assert len(effects) == 1
        assert mock_event.call_args.kwargs["instance_id"] == "room-ev-1"
        mock_event.return_value.delete.assert_called_once()
    finally:
        for p in patchers:
            p.stop()


def test_deletes_every_room_event_returned():
    h = _handler()
    events = [_room_event("room-ev-1"), _room_event("room-ev-2")]
    patchers, _, mock_event = _env(MagicMock(), room_events=events)
    try:
        mock_event.return_value.delete.return_value = MagicMock(name="delete-effect")

        assert len(h.compute()) == 2
        assert mock_event.return_value.delete.call_count == 2
    finally:
        for p in patchers:
            p.stop()


def test_lookup_receives_the_loaded_appointment():
    """The lookup needs the note and children, so it gets the model, not an id."""
    h = _handler()
    appointment = MagicMock()
    patchers, mock_find, _ = _env(appointment, room_events=[])
    try:
        h.compute()

        mock_find.assert_called_once_with(appointment)
    finally:
        for p in patchers:
            p.stop()
