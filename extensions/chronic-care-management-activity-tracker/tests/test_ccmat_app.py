"""Tests for the CCM Activity Tracker Application handler."""
import pytest
from unittest.mock import MagicMock, patch

from chronic_care_management_activity_tracker.applications.ccmat_app import CcmatApp


class TestCcmatApp:
    """Test cases for the CcmatApp application handler."""

    @patch('chronic_care_management_activity_tracker.applications.ccmat_app.LaunchModalEffect')
    def test_on_open_with_patient_id(self, mock_launch_modal):
        """Test that on_open returns a LaunchModalEffect with the correct patient ID."""
        # Arrange
        mock_effect = MagicMock()
        mock_launch_modal.return_value = mock_effect

        app = CcmatApp()
        app.event = MagicMock()
        app.event.context = {"patient": {"id": "test-patient-123"}}

        # Act
        effect = app.on_open()

        # Assert
        mock_launch_modal.assert_called_once()
        call_kwargs = mock_launch_modal.call_args.kwargs
        assert call_kwargs["title"] == "Chronic Care Management Activity Tracker"
        assert "test-patient-123" in call_kwargs["url"]
        assert call_kwargs["url"] == "/plugin-io/api/chronic_care_management_activity_tracker/test-patient-123/app"
        mock_effect.apply.assert_called_once()

    @patch('chronic_care_management_activity_tracker.applications.ccmat_app.LaunchModalEffect')
    def test_on_open_without_patient_id(self, mock_launch_modal):
        """Test that on_open handles missing patient ID gracefully."""
        # Arrange
        mock_effect = MagicMock()
        mock_launch_modal.return_value = mock_effect

        app = CcmatApp()
        app.event = MagicMock()
        app.event.context = {}

        # Act
        effect = app.on_open()

        # Assert
        mock_launch_modal.assert_called_once()
        call_kwargs = mock_launch_modal.call_args.kwargs
        assert "/None/app" in call_kwargs["url"]
        mock_effect.apply.assert_called_once()

    @patch('chronic_care_management_activity_tracker.applications.ccmat_app.LaunchModalEffect')
    def test_on_open_with_partial_patient_context(self, mock_launch_modal):
        """Test that on_open handles partial patient context."""
        # Arrange
        mock_effect = MagicMock()
        mock_launch_modal.return_value = mock_effect

        app = CcmatApp()
        app.event = MagicMock()
        app.event.context = {"patient": {}}

        # Act
        effect = app.on_open()

        # Assert
        mock_launch_modal.assert_called_once()
        call_kwargs = mock_launch_modal.call_args.kwargs
        assert "/None/app" in call_kwargs["url"]
        mock_effect.apply.assert_called_once()
