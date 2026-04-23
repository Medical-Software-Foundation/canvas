"""Tests for provider_my_panel_companion.handlers.my_panel_api."""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

from provider_my_panel_companion.handlers import my_panel_api
from provider_my_panel_companion.handlers.my_panel_api import (
    MyPanelAPI,
    _fetch_panel_patients,
    _last_appointment_by_patient,
    _next_appointment_by_patient,
    _open_task_count_by_patient,
    _serialize_patient,
)

STAFF_UUID = "00000000-0000-0000-0000-000000000001"
PATIENT_1 = "11111111-1111-1111-1111-111111111111"
PATIENT_2 = "22222222-2222-2222-2222-222222222222"


def _make_api(headers: dict | None = None) -> MyPanelAPI:
    api = MyPanelAPI.__new__(MyPanelAPI)
    api.request = SimpleNamespace(
        headers=headers or {"canvas-logged-in-user-id": STAFF_UUID},
    )
    return api


class TestFetchPanelPatients:
    def test_returns_deduped_ordered_patients(self) -> None:
        patient_a = SimpleNamespace(id=PATIENT_1, first_name="Ann", last_name="Alpha")
        patient_b = SimpleNamespace(id=PATIENT_2, first_name="Ben", last_name="Bravo")
        memberships = [
            SimpleNamespace(patient=patient_a),
            SimpleNamespace(patient=patient_a),  # duplicate — should be filtered
            SimpleNamespace(patient=None),  # null patient — should be filtered
            SimpleNamespace(patient=patient_b),
        ]
        queryset = MagicMock()
        queryset.select_related.return_value = queryset
        queryset.order_by.return_value = memberships

        with patch.object(my_panel_api, "CareTeamMembership") as mock_model:
            mock_model.objects.filter.return_value = queryset
            result = _fetch_panel_patients(STAFF_UUID)

        assert [p.id for p in result] == [PATIENT_1, PATIENT_2]
        assert mock_model.objects.filter.mock_calls[0] == call(
            staff__id=STAFF_UUID,
            status=my_panel_api.CareTeamMembershipStatus.ACTIVE,
        )
        assert queryset.mock_calls == [
            call.select_related("patient"),
            call.order_by("patient__last_name", "patient__first_name"),
        ]

    def test_empty_memberships_returns_empty(self) -> None:
        queryset = MagicMock()
        queryset.select_related.return_value = queryset
        queryset.order_by.return_value = []
        with patch.object(my_panel_api, "CareTeamMembership") as mock_model:
            mock_model.objects.filter.return_value = queryset
            assert _fetch_panel_patients(STAFF_UUID) == []


class TestAppointmentHelpers:
    NOW = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)

    def _patch_appointment_query(self, rows):
        queryset = MagicMock()
        queryset.values.return_value = queryset
        queryset.annotate.return_value = rows
        mock_model = MagicMock()
        mock_model.objects.filter.return_value = queryset
        return queryset, mock_model

    def test_last_appointment_empty_patient_list_skips_query(self) -> None:
        with patch.object(my_panel_api, "Appointment") as mock_model:
            assert _last_appointment_by_patient([], self.NOW) == {}
        assert mock_model.mock_calls == []

    def test_last_appointment_returns_dict(self) -> None:
        rows = [
            {"patient__id": PATIENT_1, "last": datetime(2026, 4, 1, 9, tzinfo=timezone.utc)},
            {"patient__id": PATIENT_2, "last": datetime(2026, 3, 15, 10, tzinfo=timezone.utc)},
        ]
        queryset, mock_model = self._patch_appointment_query(rows)
        with patch.object(my_panel_api, "Appointment", mock_model):
            result = _last_appointment_by_patient([PATIENT_1, PATIENT_2], self.NOW)

        assert result == {
            PATIENT_1: datetime(2026, 4, 1, 9, tzinfo=timezone.utc),
            PATIENT_2: datetime(2026, 3, 15, 10, tzinfo=timezone.utc),
        }
        assert mock_model.objects.filter.mock_calls[0] == call(
            patient__id__in=[PATIENT_1, PATIENT_2],
            start_time__lt=self.NOW,
        )
        assert queryset.values.mock_calls == [call("patient__id")]

    def test_next_appointment_empty_patient_list_skips_query(self) -> None:
        with patch.object(my_panel_api, "Appointment") as mock_model:
            assert _next_appointment_by_patient([], self.NOW) == {}
        assert mock_model.mock_calls == []

    def test_next_appointment_returns_dict(self) -> None:
        rows = [
            {"patient__id": PATIENT_1, "next": datetime(2026, 4, 22, 9, tzinfo=timezone.utc)},
        ]
        queryset, mock_model = self._patch_appointment_query(rows)
        with patch.object(my_panel_api, "Appointment", mock_model):
            result = _next_appointment_by_patient([PATIENT_1], self.NOW)

        assert result == {PATIENT_1: datetime(2026, 4, 22, 9, tzinfo=timezone.utc)}
        assert mock_model.objects.filter.mock_calls[0] == call(
            patient__id__in=[PATIENT_1],
            start_time__gte=self.NOW,
        )


class TestTaskCountHelper:
    def test_empty_patient_list_skips_query(self) -> None:
        with patch.object(my_panel_api, "Task") as mock_model:
            assert _open_task_count_by_patient([]) == {}
        assert mock_model.mock_calls == []

    def test_returns_counts_dict(self) -> None:
        rows = [
            {"patient__id": PATIENT_1, "count": 3},
            {"patient__id": PATIENT_2, "count": 1},
        ]
        queryset = MagicMock()
        queryset.values.return_value = queryset
        queryset.annotate.return_value = rows

        with patch.object(my_panel_api, "Task") as mock_model:
            mock_model.objects.filter.return_value = queryset
            result = _open_task_count_by_patient([PATIENT_1, PATIENT_2])

        assert result == {PATIENT_1: 3, PATIENT_2: 1}
        assert mock_model.objects.filter.mock_calls[0] == call(
            patient__id__in=[PATIENT_1, PATIENT_2],
            status=my_panel_api.TaskStatus.OPEN,
        )


class TestSerializePatient:
    def test_full_patient(self) -> None:
        patient = SimpleNamespace(id=PATIENT_1, first_name="Jane", last_name="Doe")
        result = _serialize_patient(
            patient,
            last_appointment=datetime(2026, 4, 1, 9, tzinfo=timezone.utc),
            next_appointment=datetime(2026, 4, 22, 9, tzinfo=timezone.utc),
            open_task_count=3,
        )
        assert result == {
            "id": PATIENT_1,
            "name": "Jane Doe",
            "last_appointment": "2026-04-01T09:00:00+00:00",
            "next_appointment": "2026-04-22T09:00:00+00:00",
            "open_task_count": 3,
        }

    def test_no_appointments_no_tasks(self) -> None:
        patient = SimpleNamespace(id=PATIENT_1, first_name="Jane", last_name="Doe")
        result = _serialize_patient(
            patient, last_appointment=None, next_appointment=None, open_task_count=0
        )
        assert result["last_appointment"] is None
        assert result["next_appointment"] is None
        assert result["open_task_count"] == 0

    def test_whitespace_is_stripped_from_name(self) -> None:
        patient = SimpleNamespace(id=PATIENT_1, first_name="", last_name="Doe")
        assert _serialize_patient(patient, None, None, 0)["name"] == "Doe"


class TestAuthenticate:
    def test_staff_session_passes(self) -> None:
        api = _make_api()
        creds = MagicMock(logged_in_user={"id": STAFF_UUID, "type": "Staff"})
        assert api.authenticate(creds) is True

    def test_patient_session_rejected(self) -> None:
        api = _make_api()
        creds = MagicMock(logged_in_user={"id": STAFF_UUID, "type": "Patient"})
        with pytest.raises(InvalidCredentialsError):
            api.authenticate(creds)


class TestIndex:
    def test_returns_html_with_cache_bust(self) -> None:
        api = _make_api()
        with patch.object(my_panel_api, "render_to_string", return_value="<html/>") as mock_render:
            response = api.index()[0]
        assert mock_render.mock_calls == [
            call("static/index.html", {"cache_bust": my_panel_api._CACHE_BUST})
        ]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"<html/>"
        assert response.headers["Content-Type"] == "text/html"


class TestPatientsEndpoint:
    def test_empty_panel(self) -> None:
        api = _make_api()
        with (
            patch.object(my_panel_api, "_fetch_panel_patients", return_value=[]) as mock_panel,
            patch.object(my_panel_api, "_last_appointment_by_patient", return_value={}),
            patch.object(my_panel_api, "_next_appointment_by_patient", return_value={}),
            patch.object(my_panel_api, "_open_task_count_by_patient", return_value={}),
        ):
            response = api.patients()[0]

        assert mock_panel.mock_calls == [call(STAFF_UUID)]
        assert response.status_code == HTTPStatus.OK
        assert json.loads(response.content) == {"patients": []}

    def test_assembles_response_from_helpers(self) -> None:
        api = _make_api()
        patient_1 = SimpleNamespace(id=PATIENT_1, first_name="Ann", last_name="Alpha")
        patient_2 = SimpleNamespace(id=PATIENT_2, first_name="Ben", last_name="Bravo")

        last_by = {PATIENT_1: datetime(2026, 4, 1, 9, tzinfo=timezone.utc)}
        next_by = {PATIENT_2: datetime(2026, 4, 22, 9, tzinfo=timezone.utc)}
        task_by = {PATIENT_1: 3}

        with (
            patch.object(my_panel_api, "_fetch_panel_patients", return_value=[patient_1, patient_2]),
            patch.object(my_panel_api, "_last_appointment_by_patient", return_value=last_by) as mock_last,
            patch.object(my_panel_api, "_next_appointment_by_patient", return_value=next_by) as mock_next,
            patch.object(my_panel_api, "_open_task_count_by_patient", return_value=task_by) as mock_tasks,
        ):
            response = api.patients()[0]

        payload = json.loads(response.content)["patients"]
        assert payload == [
            {
                "id": PATIENT_1,
                "name": "Ann Alpha",
                "last_appointment": "2026-04-01T09:00:00+00:00",
                "next_appointment": None,
                "open_task_count": 3,
            },
            {
                "id": PATIENT_2,
                "name": "Ben Bravo",
                "last_appointment": None,
                "next_appointment": "2026-04-22T09:00:00+00:00",
                "open_task_count": 0,
            },
        ]

        expected_uuids = [PATIENT_1, PATIENT_2]
        assert mock_last.call_args.args[0] == expected_uuids
        assert mock_next.call_args.args[0] == expected_uuids
        assert mock_tasks.mock_calls == [call(expected_uuids)]


class TestStaticEndpoints:
    def test_main_js(self) -> None:
        api = _make_api()
        with patch.object(my_panel_api, "render_to_string", return_value="// js") as mock_render:
            response = api.main_js()[0]
        assert mock_render.mock_calls == [call("static/main.js")]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"// js"
        assert response.headers["Content-Type"] == "text/javascript"

    def test_styles_css(self) -> None:
        api = _make_api()
        with patch.object(my_panel_api, "render_to_string", return_value="body{}") as mock_render:
            response = api.styles_css()[0]
        assert mock_render.mock_calls == [call("static/styles.css")]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"body{}"
        assert response.headers["Content-Type"] == "text/css"
