"""Tests for the SimpleAPI handler and Application.

The Application is trivial (one-line LaunchModalEffect emitter); the
SimpleAPI does the real work — auth, per-staff scoping, serialization,
patient hydration.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, date
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from recent_patients.applications.recent_patients_app import (
    RecentPatientsApp,
    RecentPatientsPatientApp,
)
from recent_patients.handlers.recent_patients_api import (
    ROW_LIMIT,
    RecentPatientsAPI,
    _format_dob,
    _hydrate_patients,
    _serialize_row,
)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


class TestRecentPatientsApp:
    def test_on_open_launches_modal_at_plugin_route(self) -> None:
        app = RecentPatientsApp.__new__(RecentPatientsApp)
        effect = app.on_open()
        # The LaunchModalEffect.apply() serializes payload as JSON.
        payload = json.loads(effect.payload)
        # URL includes cache-bust suffix so browsers refetch the modal HTML
        # after a deploy.
        assert payload["data"]["url"].startswith("/plugin-io/api/recent_patients/app/?v=")


class TestRecentPatientsPatientApp:
    def test_on_open_launches_same_modal_from_patient_context(self) -> None:
        app = RecentPatientsPatientApp.__new__(RecentPatientsPatientApp)
        effect = app.on_open()
        payload = json.loads(effect.payload)
        # Both surfaces point at the same SimpleAPI route — the only
        # difference is where Canvas surfaces the launcher icon.
        # URL includes cache-bust suffix so browsers refetch the modal HTML
        # after a deploy.
        assert payload["data"]["url"].startswith("/plugin-io/api/recent_patients/app/?v=")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestFormatDob:
    def test_none_returns_none(self) -> None:
        assert _format_dob(None) is None

    def test_string_returned_unchanged(self) -> None:
        assert _format_dob("1972-03-15") == "1972-03-15"

    def test_date_object_isoformatted(self) -> None:
        assert _format_dob(date(1972, 3, 15)) == "1972-03-15"

    def test_unrecognized_type_returns_none(self) -> None:
        assert _format_dob(42) is None


class TestSerializeRow:
    def _interaction(self, **overrides: Any) -> SimpleNamespace:
        base = {
            "patient_id": "pt-1",
            "interaction_type": "chart_review",
            "occurred_at": datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
        }
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_with_patient(self) -> None:
        patient = SimpleNamespace(
            id="pt-1",
            first_name="Jane",
            last_name="Doe",
            birth_date=date(1972, 3, 15),
        )
        result = _serialize_row(self._interaction(), patient)  # type: ignore[arg-type]
        assert result == {
            "patient_id": "pt-1",
            "name": "Jane Doe",
            "dob": "1972-03-15",
            "interaction_type": "chart_review",
            "occurred_at": "2026-05-14T12:00:00+00:00",
        }

    def test_without_patient_uses_placeholder(self) -> None:
        result = _serialize_row(self._interaction(), None)  # type: ignore[arg-type]
        assert result["name"] == "(unknown patient)"
        assert result["dob"] is None

    def test_empty_name_uses_placeholder(self) -> None:
        patient = SimpleNamespace(
            id="pt-1", first_name="", last_name="", birth_date=None
        )
        result = _serialize_row(self._interaction(), patient)  # type: ignore[arg-type]
        assert result["name"] == "(no name)"
        assert result["dob"] is None


class TestHydratePatients:
    def test_empty_list_does_not_query(self) -> None:
        with patch(
            "recent_patients.handlers.recent_patients_api.Patient.objects"
        ) as mgr:
            assert _hydrate_patients([]) == {}
            mgr.filter.assert_not_called()

    def test_dict_keyed_by_string_uuid(self) -> None:
        patient = SimpleNamespace(
            id="pt-aaa",
            first_name="J",
            last_name="D",
            birth_date=date(2000, 1, 1),
        )
        with patch(
            "recent_patients.handlers.recent_patients_api.Patient.objects"
        ) as mgr:
            mgr.filter.return_value.only.return_value = [patient]
            result = _hydrate_patients(["pt-aaa"])
        assert result == {"pt-aaa": patient}


# ---------------------------------------------------------------------------
# SimpleAPI routes
# ---------------------------------------------------------------------------


def _api(headers: dict[str, str] | None = None) -> RecentPatientsAPI:
    """Bypass SimpleAPI's pydantic init and attach a fake request."""
    api = RecentPatientsAPI.__new__(RecentPatientsAPI)
    api.request = SimpleNamespace(headers=headers or {}, query_params={})
    return api


class TestData:
    def test_scopes_to_logged_in_staff_and_serializes_rows(self) -> None:
        interaction = SimpleNamespace(
            patient_id="pt-1",
            interaction_type="chart_review",
            occurred_at=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
        )
        patient = SimpleNamespace(
            id="pt-1",
            first_name="Jane",
            last_name="Doe",
            birth_date=date(1972, 3, 15),
        )

        with (
            patch(
                "recent_patients.handlers.recent_patients_api"
                ".RecentPatientInteraction.objects"
            ) as int_mgr,
            patch(
                "recent_patients.handlers.recent_patients_api.Patient.objects"
            ) as pt_mgr,
        ):
            ordered = MagicMock()
            ordered.__getitem__.return_value = [interaction]
            int_mgr.filter.return_value.order_by.return_value = ordered

            pt_mgr.filter.return_value.only.return_value = [patient]

            response = _api({"canvas-logged-in-user-id": "staff-9"}).data()[0]

            # Filter is scoped to the calling staff member.
            int_mgr.filter.assert_called_once_with(staff_id="staff-9")
            # The result slice respects ROW_LIMIT.
            ordered.__getitem__.assert_called_once_with(slice(None, ROW_LIMIT))

        body = json.loads(response.content)
        assert len(body["rows"]) == 1
        row = body["rows"][0]
        assert row["patient_id"] == "pt-1"
        assert row["name"] == "Jane Doe"
        assert row["dob"] == "1972-03-15"
        assert row["interaction_type"] == "chart_review"
        assert "server_time" in body

    def test_empty_results(self) -> None:
        with (
            patch(
                "recent_patients.handlers.recent_patients_api"
                ".RecentPatientInteraction.objects"
            ) as int_mgr,
            patch(
                "recent_patients.handlers.recent_patients_api.Patient.objects"
            ) as pt_mgr,
        ):
            ordered = MagicMock()
            ordered.__getitem__.return_value = []
            int_mgr.filter.return_value.order_by.return_value = ordered

            response = _api({"canvas-logged-in-user-id": "staff-0"}).data()[0]

        body = json.loads(response.content)
        assert body["rows"] == []


class TestStaticRoutes:
    def test_index_renders_html_shell(self) -> None:
        with patch(
            "recent_patients.handlers.recent_patients_api.render_to_string"
        ) as render:
            render.return_value = "<html><body>shell</body></html>"
            result = _api().index()[0]
        assert result.status_code == HTTPStatus.OK
        # HTMLResponse stores the body in `.content`.
        assert b"shell" in result.content

    def test_main_js_returns_javascript_content_type(self) -> None:
        with patch(
            "recent_patients.handlers.recent_patients_api.render_to_string"
        ) as render:
            render.return_value = "console.log('hi');"
            result = _api().main_js()[0]
        assert result.headers["Content-Type"] == "text/javascript"
        assert b"console.log" in result.content

    def test_styles_css_returns_css_content_type(self) -> None:
        with patch(
            "recent_patients.handlers.recent_patients_api.render_to_string"
        ) as render:
            render.return_value = ".row { color: blue; }"
            result = _api().styles_css()[0]
        assert result.headers["Content-Type"] == "text/css"
        assert b"color: blue" in result.content
