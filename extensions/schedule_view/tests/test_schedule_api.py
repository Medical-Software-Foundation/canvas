"""Tests for the Schedule View plugin."""

from datetime import datetime, timezone, timedelta
from http import HTTPStatus
from unittest.mock import MagicMock, patch


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_appt(
    id="appt-001",
    patient_first="Jane",
    patient_last="Doe",
    provider_first="Dr. Alice",
    provider_last="Smith",
    provider_id="provider-1",
    patient_id="patient-1",
    location_id="loc-1",
    location_name="Main Clinic",
    note_type_id="nt-1",
    note_type_name="Med Management",
    status="confirmed",
    duration_minutes=30,
    start_time=None,
    labels=None,
    entered_in_error=None,
    comment="",
    note_id=None,
    patient_key="abc123def456",
):
    if start_time is None:
        start_time = datetime(2025, 6, 19, 9, 0, tzinfo=timezone.utc)

    appt = MagicMock()
    appt.id = id

    appt.patient_id = patient_id
    appt.patient.first_name = patient_first
    appt.patient.last_name = patient_last
    appt.patient.id = patient_key if patient_id else ""

    appt.provider_id = provider_id
    appt.provider.first_name = provider_first
    appt.provider.last_name = provider_last

    appt.location_id = location_id
    appt.location.full_name = location_name

    appt.note_type_id = note_type_id
    appt.note_type.name = note_type_name

    appt.status = status
    appt.duration_minutes = duration_minutes
    appt.start_time = start_time
    appt.comment = comment
    appt.entered_in_error = entered_in_error
    appt.note_id = note_id

    mock_labels = []
    for lbl in (labels or []):
        m = MagicMock()
        m.name = lbl["name"]
        m.color = lbl["color"]
        mock_labels.append(m)
    appt.labels.all.return_value = mock_labels

    return appt


# ── _serialize_appointment ────────────────────────────────────────────────────


class TestSerializeAppointment:
    def test_basic_fields_are_present(self):
        from schedule_view.handlers.schedule_api import _serialize_appointment

        appt = _make_appt()
        result = _serialize_appointment(appt)

        assert result["id"] == "appt-001"
        assert result["patient_name"] == "Jane Doe"
        assert result["provider_name"] == "Dr. Alice Smith"
        assert result["location_name"] == "Main Clinic"
        assert result["location_id"] == "loc-1"
        assert result["note_type_name"] == "Med Management"
        assert result["status"] == "confirmed"
        assert result["status_label"] == "Confirmed"
        assert result["status_css"] == "status-confirmed"
        assert result["duration_minutes"] == 30
        assert result["labels"] == []
        assert result["note_id"] == ""
        assert result["patient_key"] == "abc123def456"

    def test_note_id_included_when_present(self):
        from schedule_view.handlers.schedule_api import _serialize_appointment

        appt = _make_appt(note_id=42)
        result = _serialize_appointment(appt)

        assert result["note_id"] == "42"

    def test_end_time_calculated_from_duration(self):
        from schedule_view.handlers.schedule_api import _serialize_appointment

        start = datetime(2025, 6, 19, 10, 0, tzinfo=timezone.utc)
        appt = _make_appt(start_time=start, duration_minutes=45)
        result = _serialize_appointment(appt)

        expected_end = start + timedelta(minutes=45)
        assert result["end_time"] == expected_end.isoformat()

    def test_labels_serialized_with_name_and_color(self):
        from schedule_view.handlers.schedule_api import _serialize_appointment

        appt = _make_appt(labels=[
            {"name": "New Patient", "color": "green"},
            {"name": "Recurring", "color": "blue"},
        ])
        result = _serialize_appointment(appt)

        assert len(result["labels"]) == 2
        assert result["labels"][0] == {"name": "New Patient", "color": "green"}
        assert result["labels"][1] == {"name": "Recurring", "color": "blue"}

    def test_missing_provider_produces_empty_string(self):
        from schedule_view.handlers.schedule_api import _serialize_appointment

        appt = _make_appt(provider_id=None)
        result = _serialize_appointment(appt)

        assert result["provider_name"] == ""
        assert result["provider_id"] == ""

    def test_missing_location_produces_empty_strings(self):
        from schedule_view.handlers.schedule_api import _serialize_appointment

        appt = _make_appt(location_id=None)
        result = _serialize_appointment(appt)

        assert result["location_name"] == ""
        assert result["location_id"] == ""

    def test_missing_note_type_produces_empty_string(self):
        from schedule_view.handlers.schedule_api import _serialize_appointment

        appt = _make_appt(note_type_id=None)
        result = _serialize_appointment(appt)

        assert result["note_type_name"] == ""

    def test_unknown_status_maps_to_unknown_css(self):
        from schedule_view.handlers.schedule_api import _serialize_appointment

        appt = _make_appt(status="some_future_status")
        result = _serialize_appointment(appt)

        assert result["status_css"] == "status-unknown"

    def test_noshowed_status_maps_correctly(self):
        from schedule_view.handlers.schedule_api import _serialize_appointment

        appt = _make_appt(status="noshowed")
        result = _serialize_appointment(appt)

        assert result["status_label"] == "No Show"
        assert result["status_css"] == "status-noshowed"

    def test_label_missing_color_defaults_to_grey(self):
        from schedule_view.handlers.schedule_api import _serialize_appointment

        appt = _make_appt(labels=[{"name": "Urgent", "color": ""}])
        result = _serialize_appointment(appt)

        assert result["labels"][0]["color"] == "grey"

    def test_location_id_included_in_serialization(self):
        from schedule_view.handlers.schedule_api import _serialize_appointment

        appt = _make_appt(location_id="room-42", location_name="Room 42")
        result = _serialize_appointment(appt)

        assert result["location_id"] == "room-42"
        assert result["location_name"] == "Room 42"


# ── ScheduleViewAPI.appointments ─────────────────────────────────────────────


class TestScheduleViewAPIAppointments:
    def _make_handler(self, query_params=None, headers=None):
        """Build a ScheduleViewAPI instance with mocked request."""
        from schedule_view.handlers.schedule_api import ScheduleViewAPI

        mock_event = MagicMock()
        handler = ScheduleViewAPI(event=mock_event)

        mock_request = MagicMock()
        mock_request.query_params = query_params or {}
        mock_request.headers = headers or {"canvas-logged-in-user-id": "staff-1"}
        handler.request = mock_request

        return handler

    def test_returns_appointment_list_for_date(self):
        handler = self._make_handler(query_params={"date": "2025-06-19"})
        appt = _make_appt()

        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter([appt]))

        with patch(
            "schedule_view.handlers.schedule_api.Appointment.objects"
        ) as mock_mgr:
            mock_mgr.filter.return_value.exclude.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value = mock_qs

            responses = handler.appointments()

        assert len(responses) == 1
        response = responses[0]
        import json
        data = json.loads(response.content)
        assert data["date"] == "2025-06-19"
        assert len(data["appointments"]) == 1
        assert data["appointments"][0]["patient_name"] == "Jane Doe"

    def test_returns_bad_request_for_invalid_date(self):
        handler = self._make_handler(query_params={"date": "not-a-date"})

        responses = handler.appointments()

        assert len(responses) == 1
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    def test_provider_list_built_from_appointments(self):
        handler = self._make_handler(query_params={"date": "2025-06-19"})

        appt1 = _make_appt(id="a1", provider_id="p1", provider_first="Alice", provider_last="Anderson")
        appt2 = _make_appt(id="a2", provider_id="p2", provider_first="Bob", provider_last="Baker")
        appt3 = _make_appt(id="a3", provider_id="p1", provider_first="Alice", provider_last="Anderson")

        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter([appt1, appt2, appt3]))

        with patch(
            "schedule_view.handlers.schedule_api.Appointment.objects"
        ) as mock_mgr:
            mock_mgr.filter.return_value.exclude.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value = mock_qs

            responses = handler.appointments()

        import json
        data = json.loads(responses[0].content)
        # p1 only appears once in provider list
        provider_ids = [p["id"] for p in data["providers"]]
        assert provider_ids.count("p1") == 1
        assert len(data["providers"]) == 2

    def test_empty_date_defaults_to_today(self):
        handler = self._make_handler(query_params={})

        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter([]))

        with patch(
            "schedule_view.handlers.schedule_api.Appointment.objects"
        ) as mock_mgr:
            mock_mgr.filter.return_value.exclude.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value = mock_qs

            responses = handler.appointments()

        import json
        from datetime import datetime, timezone
        data = json.loads(responses[0].content)
        assert data["date"] == datetime.now(timezone.utc).date().isoformat()

    def test_appointment_includes_location_id(self):
        handler = self._make_handler(query_params={"date": "2025-06-19"})
        appt = _make_appt(location_id="loc-99", location_name="West Wing")

        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter([appt]))

        with patch(
            "schedule_view.handlers.schedule_api.Appointment.objects"
        ) as mock_mgr:
            mock_mgr.filter.return_value.exclude.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value = mock_qs

            responses = handler.appointments()

        import json
        data = json.loads(responses[0].content)
        appt_data = data["appointments"][0]
        assert appt_data["location_id"] == "loc-99"
        assert appt_data["location_name"] == "West Wing"


# ── ScheduleViewApp ──────────────────────────────────────────────────────────


class TestScheduleViewApp:
    def test_on_open_returns_launch_modal_effect(self):
        from schedule_view.applications.schedule_app import ScheduleViewApp

        mock_event = MagicMock()
        app = ScheduleViewApp(event=mock_event)

        effect = app.on_open()

        # Effect payload should reference the schedule view URL
        assert effect is not None
        import json
        payload = json.loads(effect.payload)
        # LaunchModalEffect wraps the url under payload.data.url
        url = payload.get("data", {}).get("url", payload.get("url", ""))
        assert "/plugin-io/api/schedule_view/schedule/view" in url


# ── ScheduleHomepage ─────────────────────────────────────────────────────────


class TestScheduleHomepage:
    def test_responds_to_get_homepage_configuration(self):
        from schedule_view.handlers.homepage import ScheduleHomepage
        from canvas_sdk.events import EventType

        assert ScheduleHomepage.RESPONDS_TO == EventType.Name(EventType.GET_HOMEPAGE_CONFIGURATION)

    def test_compute_returns_default_homepage_effect(self):
        from schedule_view.handlers.homepage import ScheduleHomepage
        from canvas_sdk.effects.default_homepage import DefaultHomepageEffect

        # DefaultHomepageEffect.apply() validates the application_identifier against the DB,
        # which is unavailable in unit tests. Patch _validate_before_effect to skip that check.
        with patch.object(DefaultHomepageEffect, "_validate_before_effect"):
            mock_event = MagicMock()
            handler = ScheduleHomepage(event=mock_event)

            effects = handler.compute()

        assert len(effects) == 1
        effect = effects[0]
        # .apply() returns a base Effect; verify the payload contains the right app identifier
        import json
        payload = json.loads(effect.payload)
        app_id = payload.get("data", {}).get("application_identifier", "")
        assert app_id == "schedule_view.applications.schedule_app:ScheduleViewApp"

    def test_compute_returns_list(self):
        from schedule_view.handlers.homepage import ScheduleHomepage
        from canvas_sdk.effects.default_homepage import DefaultHomepageEffect

        with patch.object(DefaultHomepageEffect, "_validate_before_effect"):
            mock_event = MagicMock()
            handler = ScheduleHomepage(event=mock_event)

            result = handler.compute()

        assert isinstance(result, list)
        assert len(result) > 0
