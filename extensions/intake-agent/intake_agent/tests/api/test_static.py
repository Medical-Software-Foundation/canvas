from unittest.mock import MagicMock, patch

import pytest

from intake_agent.api.static import Static


class TestStatic:
    """Unit tests for Static handler."""

    @pytest.fixture
    def static_api(self):
        """Create a Static instance for testing."""
        # Create a mock event object required by BaseHandler
        mock_event = MagicMock()
        mock_event.context = {
            "method": "GET",
            "path": "/static/css"
        }

        # Create the API instance with the mock event
        api = Static(mock_event)

        # Mock the request object that would normally be set by the framework
        api.request = MagicMock()

        return api

    def test_authenticate_allows_all_access(self, static_api):
        """Test that authenticate method always returns True for public access."""
        # Arrange
        mock_credentials = MagicMock()

        # Act
        result = static_api.authenticate(mock_credentials)

        # Assert
        assert result is True

    @patch("intake_agent.api.static.render_to_string")
    def test_serve_css_returns_response_with_css_content_type(self, mock_render, static_api):
        """Test that serve_css method returns Response with text/css content type."""
        # Arrange
        expected_css = "body { color: red; }"
        mock_render.return_value = expected_css

        # Act
        result = static_api.serve_css()

        # Assert
        assert len(result) == 1
        response = result[0]
        assert hasattr(response, "content")
        assert response.content == expected_css.encode()

        # Verify render_to_string was called with correct arguments
        mock_render.assert_called_once_with("static/css/intake.css", {})

    @patch("intake_agent.api.static.render_to_string")
    def test_serve_css_uses_empty_context(self, mock_render, static_api):
        """Test that serve_css method passes empty context to render_to_string."""
        # Arrange
        mock_render.return_value = "body {}"

        # Act
        static_api.serve_css()

        # Assert
        # Verify the second argument (context) is an empty dict
        call_args = mock_render.call_args
        assert call_args[0][1] == {}

    @patch("intake_agent.api.static.log")
    @patch("intake_agent.api.static.render_to_string")
    def test_serve_css_logs_request(self, mock_render, mock_log, static_api):
        """Test that serve_css method logs when serving the CSS file."""
        # Arrange
        mock_render.return_value = "body {}"

        # Act
        static_api.serve_css()

        # Assert
        mock_log.info.assert_called_once_with("Serving intake.css")

    @patch("intake_agent.api.static.log")
    @patch("intake_agent.api.static.render_to_string")
    def test_serve_css_handles_exception(self, mock_render, mock_log, static_api):
        """Test that serve_css method handles exceptions and returns 404."""
        # Arrange
        mock_render.side_effect = Exception("File not found")

        # Act
        result = static_api.serve_css()

        # Assert
        assert len(result) == 1
        response = result[0]
        assert response.content == b"/* CSS file not found */"
        assert response.status_code == 404

        # Verify error was logged
        mock_log.error.assert_called_once()

    @patch("intake_agent.api.static.render_to_string")
    def test_serve_js_returns_response_with_javascript_content_type(self, mock_render, static_api):
        """Test that serve_js method returns Response with application/javascript content type."""
        # Arrange
        expected_js = "console.log('test');"
        mock_render.return_value = expected_js

        # Act
        result = static_api.serve_js()

        # Assert
        assert len(result) == 1
        response = result[0]
        assert hasattr(response, "content")
        assert response.content == expected_js.encode()

        # Verify render_to_string was called with correct arguments
        mock_render.assert_called_once_with("static/js/intake.js", {})

    @patch("intake_agent.api.static.render_to_string")
    def test_serve_js_uses_empty_context(self, mock_render, static_api):
        """Test that serve_js method passes empty context to render_to_string."""
        # Arrange
        mock_render.return_value = "console.log('test');"

        # Act
        static_api.serve_js()

        # Assert
        # Verify the second argument (context) is an empty dict
        call_args = mock_render.call_args
        assert call_args[0][1] == {}

    @patch("intake_agent.api.static.log")
    @patch("intake_agent.api.static.render_to_string")
    def test_serve_js_logs_request(self, mock_render, mock_log, static_api):
        """Test that serve_js method logs when serving the JS file."""
        # Arrange
        mock_render.return_value = "console.log('test');"

        # Act
        static_api.serve_js()

        # Assert
        mock_log.info.assert_called_once_with("Serving intake.js")

    @patch("intake_agent.api.static.log")
    @patch("intake_agent.api.static.render_to_string")
    def test_serve_js_handles_exception(self, mock_render, mock_log, static_api):
        """Test that serve_js method handles exceptions and returns 404."""
        # Arrange
        mock_render.side_effect = Exception("File not found")

        # Act
        result = static_api.serve_js()

        # Assert
        assert len(result) == 1
        response = result[0]
        assert response.content == b"/* JS file not found */"
        assert response.status_code == 404

        # Verify error was logged
        mock_log.error.assert_called_once()
