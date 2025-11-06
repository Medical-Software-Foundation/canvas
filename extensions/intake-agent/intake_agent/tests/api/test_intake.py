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
        intake.request.path = "/intake/"
        intake.request.headers = {}
        intake.request.path_params = {}

        # Mock secrets
        intake.secrets = {"PLUGIN_SECRET_KEY": "test-secret-key"}

        return intake

    # Authentication Tests

    def test_authenticate_allows_unauthenticated_paths(self, intake_api):
        """Test that authenticate allows access to unauthenticated paths."""
        # Arrange
        mock_credentials = MagicMock()
        intake_api.request.path = "/intake/"

        # Act
        result = intake_api.authenticate(mock_credentials)

        # Assert
        assert result is True

    def test_authenticate_allows_session_creation(self, intake_api):
        """Test that authenticate allows POST to /session without auth."""
        # Arrange
        mock_credentials = MagicMock()
        intake_api.request.path = "/intake/session"

        # Act
        result = intake_api.authenticate(mock_credentials)

        # Assert
        assert result is True

    @patch("intake_agent.api.intake.verify_signature")
    def test_authenticate_requires_signature_for_protected_paths(
        self, mock_verify_signature, intake_api
    ):
        """Test that authenticate requires valid signature for protected paths."""
        # Arrange
        mock_credentials = MagicMock()
        intake_api.request.path = "/intake/message/test-session"
        intake_api.request.path_params = {"session_id": "test-session"}
        intake_api.request.headers = {"Authorization": "Signature test-signature"}
        mock_verify_signature.return_value = True

        # Act
        result = intake_api.authenticate(mock_credentials)

        # Assert
        assert result is True
        mock_verify_signature.assert_called_once_with(
            "test-session", "test-signature", "test-secret-key"
        )

    def test_authenticate_rejects_missing_authorization_header(self, intake_api):
        """Test that authenticate rejects requests without Authorization header."""
        # Arrange
        mock_credentials = MagicMock()
        intake_api.request.path = "/intake/message"
        intake_api.request.headers = {}

        # Act
        result = intake_api.authenticate(mock_credentials)

        # Assert
        assert result is False

    def test_authenticate_rejects_invalid_authorization_format(self, intake_api):
        """Test that authenticate rejects invalid Authorization header format."""
        # Arrange
        mock_credentials = MagicMock()
        intake_api.request.path = "/intake/message"
        intake_api.request.headers = {"Authorization": "Bearer invalid-format"}

        # Act
        result = intake_api.authenticate(mock_credentials)

        # Assert
        assert result is False

    @patch("intake_agent.api.intake.verify_signature")
    def test_authenticate_rejects_invalid_signature(self, mock_verify_signature, intake_api):
        """Test that authenticate rejects invalid signatures."""
        # Arrange
        mock_credentials = MagicMock()
        intake_api.request.path = "/intake/message/test-session"
        intake_api.request.path_params = {"session_id": "test-session"}
        intake_api.request.headers = {"Authorization": "Signature bad-signature"}
        mock_verify_signature.return_value = False

        # Act
        result = intake_api.authenticate(mock_credentials)

        # Assert
        assert result is False
        mock_verify_signature.assert_called_once()

    def test_authenticate_rejects_missing_secret_key(self, intake_api):
        """Test that authenticate rejects requests when PLUGIN_SECRET_KEY is missing."""
        # Arrange
        mock_credentials = MagicMock()
        intake_api.request.path = "/intake/message/test-session"
        intake_api.request.path_params = {"session_id": "test-session"}
        intake_api.request.headers = {"Authorization": "Signature test-signature"}
        intake_api.secrets = {}  # No secret key

        # Act
        result = intake_api.authenticate(mock_credentials)

        # Assert
        assert result is False

    def test_authenticate_rejects_missing_session_id_in_path_params(self, intake_api):
        """Test that authenticate rejects requests when session_id missing from path params."""
        # Arrange
        mock_credentials = MagicMock()
        intake_api.request.path = "/intake/message"
        intake_api.request.path_params = {}  # No session_id
        intake_api.request.headers = {"Authorization": "Signature test-signature"}

        # Act
        result = intake_api.authenticate(mock_credentials)

        # Assert
        assert result is False

    # Endpoint Tests

    @patch("intake_agent.api.intake.render_to_string")
    def test_get_intake_form_returns_html(self, mock_render, intake_api):
        """Test that get_intake_form returns HTMLResponse with rendered template."""
        # Arrange
        expected_html = "<html><body>Chat Interface</body></html>"
        mock_render.return_value = expected_html

        # Act
        result = intake_api.get_intake_form()

        # Assert
        assert len(result) == 1
        assert hasattr(result[0], "content")
        mock_render.assert_called_once_with("templates/intake.html", {})

    @patch("intake_agent.api.intake.log")
    @patch("intake_agent.api.intake.render_to_string")
    def test_get_intake_form_logs_request(self, mock_render, mock_log, intake_api):
        """Test that get_intake_form logs when serving the chat interface."""
        # Arrange
        mock_render.return_value = "<html></html>"

        # Act
        intake_api.get_intake_form()

        # Assert
        mock_log.info.assert_called_once_with("Serving patient intake chat interface")

    @patch("intake_agent.api.intake.generate_signature")
    @patch("intake_agent.api.intake.IntakeSessionManager.create_session")
    def test_create_session_returns_session_id_and_signature(
        self, mock_create_session, mock_generate_signature, intake_api
    ):
        """Test that create_session returns session_id and signature."""
        # Arrange
        mock_session = MagicMock()
        mock_session.session_id = "test-session-789"
        mock_create_session.return_value = mock_session
        mock_generate_signature.return_value = "test-signature-abc"

        # Act
        result = intake_api.create_session()

        # Assert
        assert len(result) == 1
        response = result[0]
        assert response.status_code == 201
        mock_create_session.assert_called_once()
        mock_generate_signature.assert_called_once_with(
            "test-session-789", "test-secret-key"
        )

    @patch("intake_agent.api.intake.IntakeSessionManager.create_session")
    def test_create_session_returns_500_when_secret_key_missing(self, mock_create_session, intake_api):
        """Test that create_session returns 500 when PLUGIN_SECRET_KEY is missing."""
        # Arrange
        mock_session = MagicMock()
        mock_session.session_id = "test-session-789"
        mock_create_session.return_value = mock_session
        intake_api.secrets = {}  # No secret key

        # Act
        result = intake_api.create_session()

        # Assert
        assert len(result) == 1
        response = result[0]
        assert response.status_code == 500

    @patch("intake_agent.api.intake.IntakeSessionManager.get_session")
    def test_get_session_data_returns_session(self, mock_get_session, intake_api):
        """Test that get_session_data returns session data."""
        # Arrange
        intake_api.request.path_params = {"session_id": "test-session"}
        mock_session = MagicMock()
        mock_session.to_dict.return_value = {
            "session_id": "test-session",
            "messages": [],
        }
        mock_get_session.return_value = mock_session

        # Act
        result = intake_api.get_session_data()

        # Assert
        assert len(result) == 1
        response = result[0]
        assert response.status_code == 200
        mock_get_session.assert_called_once_with("test-session")

    @patch("intake_agent.api.intake.IntakeSessionManager.get_session")
    def test_get_session_data_returns_404_when_not_found(self, mock_get_session, intake_api):
        """Test that get_session_data returns 404 when session not found."""
        # Arrange
        intake_api.request.path_params = {"session_id": "nonexistent"}
        mock_get_session.return_value = None

        # Act
        result = intake_api.get_session_data()

        # Assert
        assert len(result) == 1
        response = result[0]
        assert response.status_code == 404

    @patch("intake_agent.api.intake.IntakeSessionManager.get_session")
    def test_get_session_data_returns_404_on_exception(self, mock_get_session, intake_api):
        """Test that get_session_data returns 404 when get_session raises exception."""
        # Arrange
        intake_api.request.path_params = {"session_id": "error-session"}
        mock_get_session.side_effect = Exception("Cache error")

        # Act
        result = intake_api.get_session_data()

        # Assert
        assert len(result) == 1
        response = result[0]
        assert response.status_code == 404

    @patch("intake_agent.api.intake.IntakeAgent")
    @patch("intake_agent.api.intake.IntakeSessionManager.get_session")
    def test_handle_message_processes_user_message(self, mock_get_session, mock_agent_class, intake_api):
        """Test that handle_message processes user message and returns agent response."""
        # Arrange
        intake_api.request.path_params = {"session_id": "test-session"}
        intake_api.request.json = MagicMock(
            return_value={
                "message": "Hello, I need help",
            }
        )
        mock_session = MagicMock()
        mock_session.session_id = "test-session"
        mock_get_session.return_value = mock_session

        # Mock the agent instance
        mock_agent = MagicMock()
        mock_agent.session = mock_session
        mock_agent.listen.return_value = []
        mock_agent.respond.return_value = "Hello! How can I help you today?"
        mock_agent_class.return_value = mock_agent

        # Mock secrets
        intake_api.secrets = {
            "LLM_KEY": "test-key",
            "INTAKE_SCOPE_OF_CARE": "test-scope",
            "INTAKE_FALLBACK_PHONE_NUMBER": "555-0000",
            "POLICIES_URL": "https://example.com/policies",
            "TWILIO_ACCOUNT_SID": "test-sid",
            "TWILIO_AUTH_TOKEN": "test-token",
            "TWILIO_PHONE_NUMBER": "+15551234567",
        }

        # Act
        result = intake_api.handle_message()

        # Assert
        assert len(result) >= 1
        # Result is JSONResponse with agent_response
        response = result[-1]  # Last item should be the JSON response
        assert response.status_code == 200
        mock_agent.listen.assert_called_once_with("Hello, I need help")
        mock_agent.respond.assert_called_once()

    def test_handle_message_returns_400_for_missing_fields(self, intake_api):
        """Test that handle_message returns 400 when required fields are missing."""
        # Arrange
        intake_api.request.path_params = {"session_id": "test-session"}
        intake_api.request.json = MagicMock(return_value={})

        # Act
        result = intake_api.handle_message()

        # Assert
        assert len(result) == 1
        response = result[0]
        assert response.status_code == 400

    @patch("intake_agent.api.intake.IntakeSessionManager.get_session")
    def test_handle_message_returns_404_for_invalid_session(self, mock_get_session, intake_api):
        """Test that handle_message returns 404 when session doesn't exist."""
        # Arrange
        intake_api.request.path_params = {"session_id": "invalid-session"}
        intake_api.request.json = MagicMock(
            return_value={
                "message": "Hello",
            }
        )
        mock_get_session.return_value = None

        # Mock secrets
        intake_api.secrets = {
            "LLM_KEY": "test-key",
            "INTAKE_SCOPE_OF_CARE": "test-scope",
            "INTAKE_FALLBACK_PHONE_NUMBER": "555-0000",
            "POLICIES_URL": "https://example.com/policies",
            "TWILIO_ACCOUNT_SID": "test-sid",
            "TWILIO_AUTH_TOKEN": "test-token",
            "TWILIO_PHONE_NUMBER": "+15551234567",
        }

        # Act & Assert - should raise an exception when trying to create agent with None session
        with pytest.raises(AttributeError):
            intake_api.handle_message()

    @patch("intake_agent.api.intake.IntakeAgent")
    @patch("intake_agent.api.intake.IntakeSessionManager.get_session")
    def test_handle_message_handles_start_message(self, mock_get_session, mock_agent_class, intake_api):
        """Test that handle_message handles __START__ message with greeting."""
        # Arrange
        intake_api.request.path_params = {"session_id": "test-session"}
        intake_api.request.json = MagicMock(
            return_value={
                "message": "__START__",
            }
        )
        mock_session = MagicMock()
        mock_session.session_id = "test-session"
        mock_get_session.return_value = mock_session

        # Mock the agent instance
        mock_agent = MagicMock()
        mock_agent.session = mock_session
        mock_agent_class.return_value = mock_agent
        mock_agent_class.greeting.return_value = "Welcome! How can I help you today?"

        # Mock secrets
        intake_api.secrets = {
            "LLM_KEY": "test-key",
            "INTAKE_SCOPE_OF_CARE": "test-scope",
            "INTAKE_FALLBACK_PHONE_NUMBER": "555-0000",
            "POLICIES_URL": "https://example.com/policies",
            "TWILIO_ACCOUNT_SID": "test-sid",
            "TWILIO_AUTH_TOKEN": "test-token",
            "TWILIO_PHONE_NUMBER": "+15551234567",
        }

        # Act
        result = intake_api.handle_message()

        # Assert
        assert len(result) == 1
        response = result[0]
        assert response.status_code == 200
        mock_agent_class.greeting.assert_called_once()
