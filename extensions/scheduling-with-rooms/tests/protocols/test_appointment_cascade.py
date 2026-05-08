"""Tests for protocols/appointment_cascade.py.

Local cascade walks ``appointment.children`` (RR room ScheduleEvents the
booking flow created with ``parent_appointment_id`` pointing at the
patient appointment) and deletes any non-cancelled schedule_event-typed
child. Reschedules go through /book, which creates a fresh child for
the new appointment, so this handler does not run on RESCHEDULED.
"""

from unittest.mock import MagicMock, patch

from canvas_sdk.v1.data.appointment import AppointmentProgressStatus
from canvas_sdk.v1.data.note import NoteTypeCategories

from scheduling_with_rooms.protocols.appointment_cascade import (
    AppointmentCascadeHandler,
)


def _handler(appt_id: str = "appt-1") -> AppointmentCascadeHandler:
    h = AppointmentCascadeHandler.__new__(AppointmentCascadeHandler)
    event = MagicMock()
    event.target.id = appt_id
    h.event = event
    h.secrets = {}
    return h


def _child(
    child_id: str,
    category=NoteTypeCategories.SCHEDULE_EVENT,
    status=AppointmentProgressStatus.UNCONFIRMED,
    note_type: object | None = ...,
) -> MagicMock:
    """Build a child appointment mock. ``note_type=None`` simulates a
    detached child (skipped). Default builds a non-cancelled SCHEDULE_EVENT
    child that should be deleted."""
    child = MagicMock()
    child.id = child_id
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


def _appointment_with_children(children: list) -> MagicMock:
    appt = MagicMock()
    appt.children.all.return_value = children
    return appt


def test_compute_appointment_not_found_returns_empty() -> None:
    h = _handler()
    with patch(
        "scheduling_with_rooms.protocols.appointment_cascade.Appointment"
    ) as mock_appt:
        from canvas_sdk.v1.data.appointment import Appointment as Appt
        mock_appt.DoesNotExist = Appt.DoesNotExist
        mock_appt.objects.prefetch_related.return_value.get.side_effect = (
            Appt.DoesNotExist
        )
        assert h.compute() == []


def test_compute_no_children_returns_empty() -> None:
    h = _handler()
    appt = _appointment_with_children([])
    with patch(
        "scheduling_with_rooms.protocols.appointment_cascade.Appointment"
    ) as mock_appt:
        mock_appt.objects.prefetch_related.return_value.get.return_value = appt
        assert h.compute() == []


def test_compute_skips_children_without_note_type() -> None:
    h = _handler()
    appt = _appointment_with_children([_child("c1", note_type=None)])
    with patch(
        "scheduling_with_rooms.protocols.appointment_cascade.Appointment"
    ) as mock_appt:
        mock_appt.objects.prefetch_related.return_value.get.return_value = appt
        assert h.compute() == []


def test_compute_skips_non_schedule_event_children() -> None:
    h = _handler()
    appt = _appointment_with_children([
        _child("c1", category=NoteTypeCategories.ENCOUNTER),
    ])
    with patch(
        "scheduling_with_rooms.protocols.appointment_cascade.Appointment"
    ) as mock_appt:
        mock_appt.objects.prefetch_related.return_value.get.return_value = appt
        assert h.compute() == []


def test_compute_skips_already_cancelled_children() -> None:
    h = _handler()
    appt = _appointment_with_children([
        _child("c1", status=AppointmentProgressStatus.CANCELLED),
    ])
    with patch(
        "scheduling_with_rooms.protocols.appointment_cascade.Appointment"
    ) as mock_appt:
        mock_appt.objects.prefetch_related.return_value.get.return_value = appt
        assert h.compute() == []


def test_compute_deletes_active_schedule_event_child() -> None:
    h = _handler()
    appt = _appointment_with_children([_child("rr-1")])
    fake_effect = MagicMock()
    with patch(
        "scheduling_with_rooms.protocols.appointment_cascade.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.protocols.appointment_cascade.ScheduleEvent"
    ) as mock_se:
        mock_appt.objects.prefetch_related.return_value.get.return_value = appt
        mock_se.return_value.delete.return_value = fake_effect
        result = h.compute()

    assert result == [fake_effect]
    mock_se.assert_called_once_with(instance_id="rr-1")
    mock_se.return_value.delete.assert_called_once_with()


def test_compute_deletes_each_active_schedule_event_child() -> None:
    h = _handler()
    appt = _appointment_with_children([
        _child("rr-1"),
        _child("rr-2"),
        _child("cancelled", status=AppointmentProgressStatus.CANCELLED),
        _child("encounter", category=NoteTypeCategories.ENCOUNTER),
        _child("detached", note_type=None),
    ])
    eff_a = MagicMock()
    eff_b = MagicMock()
    with patch(
        "scheduling_with_rooms.protocols.appointment_cascade.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.protocols.appointment_cascade.ScheduleEvent"
    ) as mock_se:
        mock_appt.objects.prefetch_related.return_value.get.return_value = appt
        mock_se.return_value.delete.side_effect = [eff_a, eff_b]
        result = h.compute()

    assert result == [eff_a, eff_b]
    assert mock_se.call_count == 2
    constructed_ids = [c.kwargs["instance_id"] for c in mock_se.call_args_list]
    assert constructed_ids == ["rr-1", "rr-2"]
