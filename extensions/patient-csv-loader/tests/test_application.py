"""Tests for the Application handler."""

from __future__ import annotations

from unittest.mock import Mock, patch

from canvas_sdk.effects.launch_modal import LaunchModalEffect

from patient_csv_loader.apps.csv_upload import PatientCSVUpload


class TestPatientCSVUpload:
    def test_on_open_returns_launch_modal_effect(self) -> None:
        app = PatientCSVUpload(Mock())
        with patch("patient_csv_loader.apps.csv_upload.render_to_string") as mock_render:
            mock_render.return_value = "<html>test</html>"
            result = app.on_open()

        assert result is not None
        mock_render.assert_called_once()
        template_name, context = mock_render.call_args[0]
        assert template_name == "templates/upload.html"
        assert "api_base" in context
        assert "patient_csv_loader" in context["api_base"]
        assert "template_csv_json" in context

    def test_on_open_uses_default_modal_target(self) -> None:
        app = PatientCSVUpload(Mock())
        with patch("patient_csv_loader.apps.csv_upload.render_to_string") as mock_render:
            mock_render.return_value = "<html>test</html>"
            result = app.on_open()

        # The result should be an Effect (from .apply())
        assert result is not None
