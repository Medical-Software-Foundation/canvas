"""Tests for provider_schedule_companion.handlers.schedule_api."""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

from provider_schedule_companion.handlers import schedule_api
from provider_schedule_companion.handlers.schedule_api import (
    ScheduleAPI,
    _parse_iso,
    _serialize_appointment,
)

STAFF_UUID = "00000000-0000-0000-0000-000000000001"


def _make_api(headers: dict | None = None, query_params: dict | None = None) -> ScheduleAPI:
    api = ScheduleAPI.__new__(ScheduleAPI)
    api.request = SimpleNamespace(
        headers=headers or {"canvas-logged-in-user-id": STAFF_UUID},
        query_params=query_params or {},
    )
    return api


class TestParseIso:
    def test_accepts_z_suffix(self) -> None:
        assert _parse_iso("2026-04-17T00:00:00Z") == datetime(
            2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc
        )

    def test_accepts_offset(self) -> None:
        parsed = _parse_iso("2026-04-17T00:00:00+00:00")
        assert parsed.utcoffset().total_seconds() == 0

    def test_rejects_invalid(self) -> None:
        with pytest.raises(ValueError):
            _parse_iso("not-a-date")


class TestSerializeAppointment:
    def test_full_appointment(self) -> None:
        appt = SimpleNamespace(
            id="appt-1",
            start_time=datetime(2026, 4, 17, 9, 0, tzinfo=timezone.utc),
            duration_minutes=30,
            patient=SimpleNamespace(id="pat-uuid", first_name="Jane", last_name="Doe"),
            note_type=SimpleNamespace(name="Follow-up"),
            description="Back pain",
            status="confirmed",
        )

        assert _serialize_appointment(appt) == {
            "id": "appt-1",
            "start_time": "2026-04-17T09:00:00+00:00",
            "duration_minutes": 30,
            "patient_id": "pat-uuid",
            "patient_name": "Jane Doe",
            "appointment_type": "Follow-up",
            "reason_for_visit": "Back pain",
            "status": "confirmed",
        }

    def test_null_patient_and_note_type(self) -> None:
        appt = SimpleNamespace(
            id="appt-2",
            start_time=datetime(2026, 4, 17, 9, 0, tzinfo=timezone.utc),
            duration_minutes=15,
            patient=None,
            note_type=None,
            description=None,
            status=None,
        )

        result = _serialize_appointment(appt)

        assert result["patient_id"] == ""
        assert result["patient_name"] == ""
        assert result["appointment_type"] == ""
        assert result["reason_for_visit"] == ""
        assert result["status"] == ""

    def test_null_start_time(self) -> None:
        appt = SimpleNamespace(
            id="appt-3",
            start_time=None,
            duration_minutes=0,
            patient=None,
            note_type=None,
            description="",
            status="",
        )

        assert _serialize_appointment(appt)["start_time"] is None


class TestAuthenticate:
    def test_staff_session_passes(self) -> None:
        api = _make_api()
        credentials = MagicMock(logged_in_user={"id": STAFF_UUID, "type": "Staff"})
        assert api.authenticate(credentials) is True

    def test_patient_session_rejected(self) -> None:
        api = _make_api()
        credentials = MagicMock(logged_in_user={"id": STAFF_UUID, "type": "Patient"})
        with pytest.raises(InvalidCredentialsError):
            api.authenticate(credentials)


class TestIndex:
    def test_returns_html_response(self) -> None:
        api = _make_api()
        with patch.object(schedule_api, "render_to_string", return_value="<html>x</html>") as mock_render:
            result = api.index()

        assert mock_render.mock_calls == [call("static/index.html", {})]
        response = result[0]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"<html>x</html>"
        assert response.headers["Content-Type"] == "text/html"


class TestAppointments:
    def test_missing_params_returns_400(self) -> None:
        api = _make_api(query_params={})
        response = api.appointments()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert b"required" in response.content

    def test_missing_end_only_returns_400(self) -> None:
        api = _make_api(query_params={"start": "2026-04-17T00:00:00Z"})
        response = api.appointments()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_iso_returns_400(self) -> None:
        api = _make_api(query_params={"start": "junk", "end": "junk"})
        response = api.appointments()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert b"ISO-8601" in response.content

    def test_success_returns_serialized_appointments(self) -> None:
        api = _make_api(
            query_params={
                "start": "2026-04-17T00:00:00Z",
                "end": "2026-04-18T00:00:00Z",
            }
        )

        appt = SimpleNamespace(
            id="a1",
            start_time=datetime(2026, 4, 17, 9, tzinfo=timezone.utc),
            duration_minutes=30,
            patient=SimpleNamespace(id="pat-1", first_name="Jane", last_name="Doe"),
            note_type=SimpleNamespace(name="Visit"),
            description="chk",
            status="confirmed",
        )

        queryset = MagicMock()
        queryset.select_related.return_value = queryset
        queryset.order_by.return_value = [appt]

        with patch.object(schedule_api, "Appointment") as mock_appt:
            mock_appt.objects.filter.return_value = queryset
            response = api.appointments()[0]

        assert mock_appt.objects.filter.mock_calls[0] == call(
            provider__id=STAFF_UUID,
            start_time__gte=datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc),
            start_time__lt=datetime(2026, 4, 18, 0, 0, 0, tzinfo=timezone.utc),
        )
        assert queryset.mock_calls == [
            call.select_related("patient", "note_type"),
            call.order_by("start_time"),
        ]

        assert response.status_code == HTTPStatus.OK
        payload = json.loads(response.content)
        assert payload["appointments"][0]["id"] == "a1"
        assert payload["appointments"][0]["patient_name"] == "Jane Doe"


class TestStaticEndpoints:
    def test_main_js(self) -> None:
        api = _make_api()
        with patch.object(schedule_api, "render_to_string", return_value="// js") as mock_render:
            response = api.main_js()[0]
        assert mock_render.mock_calls == [call("static/main.js")]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"// js"
        assert response.headers["Content-Type"] == "text/javascript"

    def test_styles_css(self) -> None:
        api = _make_api()
        with patch.object(schedule_api, "render_to_string", return_value="body{}") as mock_render:
            response = api.styles_css()[0]
        assert mock_render.mock_calls == [call("static/styles.css")]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"body{}"
        assert response.headers["Content-Type"] == "text/css"
