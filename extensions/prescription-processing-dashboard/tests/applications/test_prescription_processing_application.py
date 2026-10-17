"""Tests for PrescriptionProcessingApplication."""

from unittest.mock import MagicMock, call, patch

from prescription_processing_dashboard.applications.prescription_processing_application import (
    PrescriptionProcessingApplication,
)


class TestPrescriptionProcessingApplication:
    """Tests for the PrescriptionProcessingApplication class."""

    def test_on_open_returns_launch_modal_effect(self, mock_event):
        """Test that on_open returns a LaunchModalEffect with the correct URL."""
        with patch(
            "prescription_processing_dashboard.applications.prescription_processing_application.LaunchModalEffect"
        ) as mock_launch_modal:
            mock_effect = MagicMock()
            mock_launch_modal.return_value.apply.return_value = mock_effect

            app = PrescriptionProcessingApplication(event=mock_event)
            result = app.on_open()

            # Verify mock_launch_modal
            assert mock_launch_modal.mock_calls == [
                call(
                    url="/plugin-io/api/prescription_processing_dashboard/app/dashboard",
                    target=mock_launch_modal.TargetType.PAGE,
                ),
                call().apply(),
            ]

            # Verify mock_event (not accessed during on_open)
            assert mock_event.mock_calls == []

            # Verify result
            assert result == mock_effect

    def test_on_open_uses_page_target_type(self, mock_event):
        """Test that on_open uses PAGE as the target type for full-page modal."""
        with patch(
            "prescription_processing_dashboard.applications.prescription_processing_application.LaunchModalEffect"
        ) as mock_launch_modal:
            mock_launch_modal.TargetType.PAGE = "PAGE"
            mock_effect = MagicMock()
            mock_launch_modal.return_value.apply.return_value = mock_effect

            app = PrescriptionProcessingApplication(event=mock_event)
            app.on_open()

            # Verify the target type was PAGE
            assert mock_launch_modal.mock_calls == [
                call(
                    url="/plugin-io/api/prescription_processing_dashboard/app/dashboard",
                    target="PAGE",
                ),
                call().apply(),
            ]

            # Verify mock_event (not accessed during on_open)
            assert mock_event.mock_calls == []
