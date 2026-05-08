"""Tests for patient_chart_app.py."""

from unittest.mock import MagicMock, patch

from scheduling_with_rooms.applications.patient_chart_app import (
    PatientChartSchedulingWithRoomsApp,
)


def test_on_open_with_patient_id_appends_query_param():
    handler = PatientChartSchedulingWithRoomsApp.__new__(
        PatientChartSchedulingWithRoomsApp
    )
    handler.event = MagicMock()
    handler.event.context = {"patient": {"id": "patient-xyz"}}

    fake_effect = MagicMock(name="fake_effect")
    with patch(
        "scheduling_with_rooms.applications.patient_chart_app.LaunchModalEffect"
    ) as mock_modal:
        mock_modal.TargetType.DEFAULT_MODAL = "DEFAULT_MODAL"
        mock_modal.return_value.apply.return_value = fake_effect

        result = handler.on_open()

        kwargs = mock_modal.mock_calls[0].kwargs
        assert kwargs["url"].startswith("/plugin-io/api/scheduling_with_rooms/modal?v=")
        assert "&patient_id=patient-xyz" in kwargs["url"]
        assert kwargs["target"] == "DEFAULT_MODAL"
        assert kwargs["title"] == "Schedule Appointment"
        assert result is fake_effect


def test_on_open_without_patient_id_omits_query_param():
    handler = PatientChartSchedulingWithRoomsApp.__new__(
        PatientChartSchedulingWithRoomsApp
    )
    handler.event = MagicMock()
    handler.event.context = {}

    fake_effect = MagicMock(name="fake_effect")
    with patch(
        "scheduling_with_rooms.applications.patient_chart_app.LaunchModalEffect"
    ) as mock_modal:
        mock_modal.TargetType.DEFAULT_MODAL = "DEFAULT_MODAL"
        mock_modal.return_value.apply.return_value = fake_effect

        result = handler.on_open()

        kwargs = mock_modal.mock_calls[0].kwargs
        # Cache-bust is present, but no patient_id since context was empty.
        assert kwargs["url"].startswith("/plugin-io/api/scheduling_with_rooms/modal?v=")
        assert "patient_id" not in kwargs["url"]
        assert kwargs["target"] == "DEFAULT_MODAL"
        assert kwargs["title"] == "Schedule Appointment"
        assert result is fake_effect
