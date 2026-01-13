"""Tests for the labs_app Application handler."""

import pytest
from unittest.mock import patch, MagicMock

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect

from portal_content.views.labs_app import LabReportsApp


class TestLabReportsApp:
    """Tests for LabReportsApp Application handler."""

    def test_on_open_returns_launch_modal_effect(self):
        """Test that on_open returns LaunchModalEffect when enabled."""
        app = MagicMock(spec=LabReportsApp)
        app.secrets = {}
        app.event = MagicMock()
        app.event.context = {"user": {"id": "patient-123"}}

        with patch("portal_content.views.labs_app.is_component_enabled") as mock_enabled:
            with patch("portal_content.views.labs_app.log"):
                mock_enabled.return_value = True
                result = LabReportsApp.on_open(app)

        mock_enabled.assert_called_once_with("labs", app.secrets)
        # Result should be a LaunchModalEffect applied (returns an Effect)
        assert isinstance(result, Effect)
        assert "LAUNCH_MODAL" in str(result)
        assert "/plugin-io/api/portal_content/labs/portal" in str(result)

    def test_on_open_returns_empty_when_disabled(self):
        """Test that on_open returns empty list when component disabled."""
        app = MagicMock(spec=LabReportsApp)
        app.secrets = {"ENABLED_COMPONENTS": "imaging"}
        app.event = MagicMock()
        app.event.context = {"user": {"id": "patient-123"}}

        with patch("portal_content.views.labs_app.is_component_enabled") as mock_enabled:
            with patch("portal_content.views.labs_app.log"):
                mock_enabled.return_value = False
                result = LabReportsApp.on_open(app)

        mock_enabled.assert_called_once_with("labs", app.secrets)
        assert result == []

    def test_on_open_uses_patient_context_fallback(self):
        """Test that on_open falls back to patient context when user id missing."""
        app = MagicMock(spec=LabReportsApp)
        app.secrets = {}
        app.event = MagicMock()
        app.event.context = {"user": {}, "patient": {"id": "patient-456"}}

        with patch("portal_content.views.labs_app.is_component_enabled") as mock_enabled:
            with patch("portal_content.views.labs_app.log"):
                mock_enabled.return_value = True
                result = LabReportsApp.on_open(app)

        assert isinstance(result, Effect)
        assert "LAUNCH_MODAL" in str(result)

    def test_on_open_returns_empty_when_no_patient_id(self):
        """Test that on_open returns empty list when no patient id found."""
        app = MagicMock(spec=LabReportsApp)
        app.secrets = {}
        app.event = MagicMock()
        app.event.context = {"user": {}, "patient": {}}

        with patch("portal_content.views.labs_app.is_component_enabled") as mock_enabled:
            with patch("portal_content.views.labs_app.log"):
                mock_enabled.return_value = True
                result = LabReportsApp.on_open(app)

        assert result == []

    def test_on_open_handles_missing_context_keys(self):
        """Test that on_open handles missing context keys gracefully."""
        app = MagicMock(spec=LabReportsApp)
        app.secrets = {}
        app.event = MagicMock()
        app.event.context = {}

        with patch("portal_content.views.labs_app.is_component_enabled") as mock_enabled:
            with patch("portal_content.views.labs_app.log"):
                mock_enabled.return_value = True
                result = LabReportsApp.on_open(app)

        assert result == []
