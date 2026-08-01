"""Tests for scheduling_with_rooms_app.py."""

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from canvas_sdk.handlers.application import SchedulingApplication

from scheduling_with_rooms.applications.scheduling_with_rooms_app import (
    SchedulingWithRoomsApp,
)


def _open(context):
    """Run on_open with LaunchModalEffect stubbed; return its ctor kwargs."""
    handler = SchedulingWithRoomsApp.__new__(SchedulingWithRoomsApp)
    handler.event = MagicMock()
    handler.event.context = context

    fake_effect = MagicMock(name="fake_effect")
    with patch(
        "scheduling_with_rooms.applications.scheduling_with_rooms_app.LaunchModalEffect"
    ) as mock_modal:
        mock_modal.TargetType.DEFAULT_MODAL = "DEFAULT_MODAL"
        mock_modal.return_value.apply.return_value = fake_effect

        result = handler.on_open()

    assert result is fake_effect
    return mock_modal.call_args.kwargs


def _params(url):
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


def test_registers_as_scheduling_modal_override():
    assert issubclass(SchedulingWithRoomsApp, SchedulingApplication)
    assert SchedulingWithRoomsApp.IDENTIFIER == "scheduling_with_rooms__scheduler"
    assert SchedulingWithRoomsApp.NAME == "Schedule Appointment"


def test_empty_context_still_opens_the_modal():
    kwargs = _open({})
    params = _params(kwargs["url"])

    assert urlparse(kwargs["url"]).path == "/plugin-io/api/scheduling_with_rooms/modal"
    assert set(params) == {"v"}
    assert kwargs["target"] == "DEFAULT_MODAL"
    assert kwargs["title"] == "Schedule Appointment"


def test_schedule_page_origin_forwards_start_and_mode():
    kwargs = _open({
        "start": "2026-08-03T14:00:00+00:00",
        "mode": "schedule",
        "origin": "schedule_page",
    })
    params = _params(kwargs["url"])

    assert params["start"] == "2026-08-03T14:00:00+00:00"
    assert params["mode"] == "schedule"
    assert params["origin"] == "schedule_page"
    assert "patient_id" not in params


def test_patient_chart_origin_forwards_patient_id():
    kwargs = _open({
        "patient": {"id": "patient-xyz"},
        "start": "2026-08-03T14:00:00+00:00",
        "mode": "schedule",
        "origin": "patient_chart",
    })
    params = _params(kwargs["url"])

    assert params["patient_id"] == "patient-xyz"
    assert kwargs["title"] == "Schedule Appointment"


def test_calendar_origin_forwards_provider_location_and_end():
    kwargs = _open({
        "provider": {"id": "staff-1"},
        "location": {"id": "loc-1"},
        "start": "2026-08-03T14:00:00+00:00",
        "end": "2026-08-03T14:30:00+00:00",
        "mode": "schedule",
        "origin": "calendar",
    })
    params = _params(kwargs["url"])

    assert params["provider_id"] == "staff-1"
    assert params["location_id"] == "loc-1"
    assert params["end"] == "2026-08-03T14:30:00+00:00"
    assert "duration" not in params


def test_note_reschedule_origin_forwards_all_entities_and_titles_reschedule():
    kwargs = _open({
        "appointment": {"id": "appt-1"},
        "note": {"id": "note-1"},
        "patient": {"id": "patient-xyz"},
        "start": "2026-08-03T14:00:00+00:00",
        "duration": 45,
        "mode": "reschedule",
        "origin": "note_reschedule",
    })
    params = _params(kwargs["url"])

    assert params["appointment_id"] == "appt-1"
    assert params["note_id"] == "note-1"
    assert params["patient_id"] == "patient-xyz"
    assert params["duration"] == "45"
    assert kwargs["title"] == "Reschedule Appointment"


def test_entity_without_id_is_dropped():
    kwargs = _open({"patient": {}, "provider": None, "location": "not-a-dict"})
    params = _params(kwargs["url"])

    assert set(params) == {"v"}


def test_blank_scalars_are_dropped():
    kwargs = _open({"start": "", "mode": "", "origin": None, "duration": 0})
    params = _params(kwargs["url"])

    # duration=0 is falsy but not blank, so it survives; the rest don't.
    assert set(params) == {"v", "duration"}
