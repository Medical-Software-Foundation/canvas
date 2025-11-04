from unittest.mock import MagicMock, patch

import pytest

from intake_agent.api.intake import IntakeAPI


class TestIntakeAPI:
    """Unit tests for IntakeAPI handler."""

    @pytest.fixture
    def intake_api(self):
        """Create an IntakeAPI instance for testing."""
        # Create a mock event object required by BaseHandler
        mock_event = MagicMock()
        mock_event.context = {
            "method": "GET",
            "path": "/intake"
        }

        # Create the API instance with the mock event
        intake = IntakeAPI(mock_event)

        # Mock the request object that would normally be set by the framework
        intake.request = MagicMock()

        return intake

    def test_authenticate_allows_all_access(self, intake_api):
        """Test that authenticate method always returns True for public access."""
        # Arrange
        mock_credentials = MagicMock()

        # Act
        result = intake_api.authenticate(mock_credentials)

        # Assert
        assert result is True

    @patch("intake_agent.api.intake.render_to_string")
    def test_get_returns_html_response(self, mock_render, intake_api):
        """Test that get_intake_form method returns HTMLResponse with rendered template."""
        # Arrange
        expected_html = "<html><body>Test HTML</body></html>"
        mock_render.return_value = expected_html

        # Act
        result = intake_api.get_intake_form()

        # Assert
        assert len(result) == 1
        response = result[0]
        assert hasattr(response, "content")

        # Verify render_to_string was called with correct arguments
        mock_render.assert_called_once_with("templates/intake.html", {})

    @patch("intake_agent.api.intake.render_to_string")
    def test_get_uses_empty_context(self, mock_render, intake_api):
        """Test that get_intake_form method passes empty context to render_to_string."""
        # Arrange
        mock_render.return_value = "<html></html>"

        # Act
        intake_api.get_intake_form()

        # Assert
        # Verify the second argument (context) is an empty dict
        call_args = mock_render.call_args
        assert call_args[0][1] == {}

    @patch("intake_agent.api.intake.log")
    @patch("intake_agent.api.intake.render_to_string")
    def test_get_logs_request(self, mock_render, mock_log, intake_api):
        """Test that get_intake_form method logs when serving the intake form."""
        # Arrange
        mock_render.return_value = "<html></html>"

        # Act
        intake_api.get_intake_form()

        # Assert
        mock_log.info.assert_called_once_with("Serving patient intake form")
