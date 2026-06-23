"""Tests for protocols/rr_event_origination.py."""

import datetime
from unittest.mock import MagicMock, patch

from scheduling_with_rooms.protocols.rr_event_origination import RREventOrigination


def _handler(appt_id: str = "appt-1") -> RREventOrigination:
    h = RREventOrigination.__new__(RREventOrigination)
    event = MagicMock()
    event.target.id = appt_id
    h.event = event
    h.secrets = {}
    return h


def _appointment() -> MagicMock:
    appt = MagicMock()
    appt.id = "appt-1"
    appt.patient = MagicMock(id="pt-1")
    appt.provider = MagicMock(id="prov-1")
    appt.start_time = datetime.datetime(2026, 5, 7, 10, 0)
    return appt


def _intent(**overrides) -> dict:
    intent = {
        "rr_staff_id": "rr-1",
        "note_type_id": "07071c25-3317-4883-bc21-180d8d87568e",
        "duration_minutes": 30,
        "location_id": "loc-1",
        "description": "fever",
    }
    intent.update(overrides)
    return intent


def test_compute_appointment_not_found_returns_empty() -> None:
    h = _handler()
    with patch(
        "scheduling_with_rooms.protocols.rr_event_origination.Appointment"
    ) as mock_appt:
        from canvas_sdk.v1.data.appointment import Appointment as Appt

        mock_appt.DoesNotExist = Appt.DoesNotExist
        mock_appt.objects.select_related.return_value.get.side_effect = Appt.DoesNotExist
        assert h.compute() == []


def test_compute_no_intent_returns_empty() -> None:
    h = _handler()
    with patch(
        "scheduling_with_rooms.protocols.rr_event_origination.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.protocols.rr_event_origination.pop_rr_event",
        return_value=None,
    ):
        mock_appt.objects.select_related.return_value.get.return_value = _appointment()
        assert h.compute() == []


def test_compute_omits_description_even_when_cached() -> None:
    """The room ScheduleEvent must never carry a description, even when the
    cached booking intent still holds one — the room note type can read its
    allow_custom_title off an inactive version and reject it."""
    h = _handler()
    fake_effect = MagicMock(name="effect")
    with patch(
        "scheduling_with_rooms.protocols.rr_event_origination.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.protocols.rr_event_origination.pop_rr_event",
        return_value=_intent(),
    ), patch(
        "scheduling_with_rooms.protocols.rr_event_origination.ScheduleEvent"
    ) as mock_se:
        mock_appt.objects.select_related.return_value.get.return_value = _appointment()
        mock_se.return_value.create.return_value = fake_effect

        result = h.compute()

    assert result == [fake_effect]
    mock_se.assert_called_once()
    kwargs = mock_se.call_args.kwargs
    assert "description" not in kwargs
    assert kwargs["note_type_id"] == "07071c25-3317-4883-bc21-180d8d87568e"
    assert kwargs["patient_id"] == "pt-1"
    assert kwargs["provider_id"] == "rr-1"
    assert kwargs["parent_appointment_id"] == "appt-1"
