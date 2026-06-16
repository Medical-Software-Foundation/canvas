import json
from unittest.mock import MagicMock

from scheduling_app.applications.scheduling_app import SchedulingApp

from canvas_sdk.handlers.application import ApplicationScope


def _app_with_context(context: dict) -> SchedulingApp:
    """Build a SchedulingApp whose event carries the given context."""
    event = MagicMock()
    event.context = context
    return SchedulingApp(event=event)


def _launched_url(app: SchedulingApp) -> str:
    """Return the URL the app's on_open LaunchModalEffect points at."""
    effect = app.on_open()
    return json.loads(effect.payload)["data"]["url"]


def test_scheduling_app_uses_scheduling_scope() -> None:
    """The example app declares the scheduling scope."""
    assert SchedulingApp.SCOPE == ApplicationScope.SCHEDULING
    assert SchedulingApp.NAME == "Schedule"


def test_on_open_forwards_calendar_context() -> None:
    """Calendar drag-and-drop context (origin/start/end/provider) is forwarded to the URL."""
    url = _launched_url(
        _app_with_context(
            {
                "mode": "schedule",
                "origin": "calendar",
                "start": "2026-06-04T09:00:00",
                "end": "2026-06-04T09:30:00",
                "provider": {"id": "staff-key-1"},
                "location": {"id": "loc-uuid-1"},
            }
        )
    )

    assert url.startswith("/plugin-io/api/scheduling_app/app/modal?")
    assert "mode=schedule" in url
    assert "origin=calendar" in url
    assert "start=2026-06-04T09:00:00" in url
    assert "end=2026-06-04T09:30:00" in url
    assert "provider_id=staff-key-1" in url
    assert "location_id=loc-uuid-1" in url
    # No patient is available on the calendar entry point.
    assert "patient_id=" not in url


def test_on_open_forwards_patient_note_and_appointment() -> None:
    """Reschedule context (patient, note, appointment as {id} objects) is forwarded."""
    url = _launched_url(
        _app_with_context(
            {
                "mode": "reschedule",
                "origin": "note_reschedule",
                "duration": 30,
                "appointment": {"id": "appt-uuid-9"},
                "patient": {"id": "pat-7"},
                "note": {"id": "note-3"},
            }
        )
    )

    assert "mode=reschedule" in url
    assert "origin=note_reschedule" in url
    assert "duration=30" in url
    assert "appointment_id=appt-uuid-9" in url
    assert "patient_id=pat-7" in url
    assert "note_id=note-3" in url


def test_on_open_without_context_has_no_query_string() -> None:
    """With no context supplied, the launched URL carries no query string."""
    url = _launched_url(_app_with_context({}))

    assert url == "/plugin-io/api/scheduling_app/app/modal"
