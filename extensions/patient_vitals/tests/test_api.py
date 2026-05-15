"""Tests for VitalsAPI - routing, security boundaries, and error handling."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

from patient_vitals.api import VitalsAPI
from patient_vitals.vitals_data import UnknownVitalCode


# ---------- auth mixin behaviour ------------------------------------------


def test_authenticate_succeeds_for_patient_user(mock_patient_credentials) -> None:
    """PatientSessionAuthMixin accepts a logged-in patient."""
    mock_self = MagicMock()
    assert VitalsAPI.authenticate(mock_self, mock_patient_credentials) is True


def test_authenticate_rejects_staff_user(mock_staff_credentials) -> None:
    """PatientSessionAuthMixin rejects staff sessions outright."""
    mock_self = MagicMock()
    with pytest.raises(InvalidCredentialsError):
        VitalsAPI.authenticate(mock_self, mock_staff_credentials)


def test_authenticate_rejects_anonymous_user() -> None:
    """Anonymous sessions (no logged_in_user) are not allowed."""
    mock_self = MagicMock()
    credentials = MagicMock()
    credentials.logged_in_user = None
    with pytest.raises((InvalidCredentialsError, TypeError, KeyError)):
        VitalsAPI.authenticate(mock_self, credentials)


# ---------- /page ---------------------------------------------------------


def test_page_returns_html_response(mock_request) -> None:
    """The page route returns one HTMLResponse with status 200."""
    mock_self = MagicMock()
    mock_self.request = mock_request

    with patch("patient_vitals.api.render_to_string", return_value="<html></html>"):
        with patch("patient_vitals.api.log"):
            result = VitalsAPI.page(mock_self)

    assert len(result) == 1
    response = result[0]
    assert response.status_code == HTTPStatus.OK


# ---------- /observations dispatch ----------------------------------------


def _api_with_body(body: dict, header_patient: str = "patient-123") -> MagicMock:
    """Build a VitalsAPI mock with the given JSON body and header patient id."""
    mock_self = MagicMock()
    mock_self.request = MagicMock()
    mock_self.request.headers = MagicMock()
    mock_self.request.headers.get.return_value = header_patient
    mock_self.request.json.return_value = body
    return mock_self


def test_observations_dispatches_list_summary() -> None:
    """``list_summary`` calls aggregate_summary with the header patient id."""
    api = _api_with_body({"action": "list_summary"})

    summary = [{"code": "pulse", "reading_count": 3}]
    with patch(
        "patient_vitals.api.aggregate_summary", return_value=summary
    ) as mock_agg:
        with patch("patient_vitals.api.log"):
            result = VitalsAPI.observations(api)

    mock_agg.assert_called_once_with("patient-123")
    response = result[0]
    assert response.status_code == HTTPStatus.OK


def test_observations_dispatches_history() -> None:
    """``history`` calls history_for_code with the header patient id and body code."""
    api = _api_with_body({"action": "history", "code": "pulse"})

    payload = {"code": "pulse", "display_name": "Pulse", "unit": "bpm", "series": []}
    with patch(
        "patient_vitals.api.history_for_code", return_value=payload
    ) as mock_hist:
        with patch("patient_vitals.api.log"):
            result = VitalsAPI.observations(api)

    mock_hist.assert_called_once_with("patient-123", "pulse")
    assert result[0].status_code == HTTPStatus.OK


def test_observations_unknown_action_returns_400() -> None:
    """An unrecognised action is rejected with HTTP 400."""
    api = _api_with_body({"action": "nope"})

    with patch("patient_vitals.api.log"):
        result = VitalsAPI.observations(api)

    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_observations_unknown_code_returns_400() -> None:
    """``UnknownVitalCode`` raised by the data layer maps to HTTP 400."""
    api = _api_with_body({"action": "history", "code": "not_a_code"})

    with patch(
        "patient_vitals.api.history_for_code",
        side_effect=UnknownVitalCode("not_a_code"),
    ):
        with patch("patient_vitals.api.log"):
            result = VitalsAPI.observations(api)

    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_observations_unexpected_exception_returns_500() -> None:
    """Any other exception is caught and mapped to HTTP 500."""
    api = _api_with_body({"action": "list_summary"})

    with patch(
        "patient_vitals.api.aggregate_summary", side_effect=RuntimeError("boom")
    ):
        with patch("patient_vitals.api.log"):
            result = VitalsAPI.observations(api)

    assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ---------- security: body-spoofed patient_id MUST be ignored -------------


def test_observations_ignores_body_patient_id_on_list_summary() -> None:
    """A spoofed ``patient_id`` field in the body must not reach the data layer."""
    api = _api_with_body(
        {"action": "list_summary", "patient_id": "attacker-target"},
        header_patient="patient-123",
    )

    with patch("patient_vitals.api.aggregate_summary", return_value=[]) as mock_agg:
        with patch("patient_vitals.api.log"):
            VitalsAPI.observations(api)

    # Single positional arg, the value from the header, never "attacker-target".
    mock_agg.assert_called_once_with("patient-123")


def test_observations_ignores_body_patient_id_on_history() -> None:
    """Same guarantee for the history action."""
    api = _api_with_body(
        {"action": "history", "code": "pulse", "patient_id": "attacker-target"},
        header_patient="patient-123",
    )

    with patch(
        "patient_vitals.api.history_for_code",
        return_value={
            "code": "pulse",
            "display_name": "Pulse",
            "unit": "bpm",
            "series": [],
        },
    ) as mock_hist:
        with patch("patient_vitals.api.log"):
            VitalsAPI.observations(api)

    mock_hist.assert_called_once_with("patient-123", "pulse")
