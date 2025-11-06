import base64
from unittest.mock import MagicMock, patch

import pytest
import requests

from intake_agent.twilio_client import TwilioClient


class TestTwilioClient:
    """Unit tests for TwilioClient."""

    @pytest.fixture
    def twilio_client(self):
        """Create a TwilioClient instance for testing."""
        return TwilioClient(
            account_sid="AC123456789",
            auth_token="test_auth_token_123"
        )

    # Initialization Tests

    def test_init_sets_account_sid(self, twilio_client):
        """Test that __init__ sets the account_sid."""
        assert twilio_client.account_sid == "AC123456789"

    def test_init_sets_auth_token(self, twilio_client):
        """Test that __init__ sets the auth_token."""
        assert twilio_client.auth_token == "test_auth_token_123"

    def test_init_constructs_base_url(self, twilio_client):
        """Test that __init__ constructs the correct base_url."""
        expected_url = "https://api.twilio.com/2010-04-01/Accounts/AC123456789"
        assert twilio_client.base_url == expected_url

    # Auth Header Tests

    def test_get_auth_header_returns_basic_auth(self, twilio_client):
        """Test that _get_auth_header returns properly formatted Basic auth."""
        auth_header = twilio_client._get_auth_header()
        assert auth_header.startswith("Basic ")

    def test_get_auth_header_encodes_credentials_correctly(self, twilio_client):
        """Test that _get_auth_header encodes credentials in base64."""
        auth_header = twilio_client._get_auth_header()
        encoded_part = auth_header.replace("Basic ", "")

        # Decode and verify
        decoded = base64.b64decode(encoded_part).decode()
        assert decoded == "AC123456789:test_auth_token_123"

    # Send SMS Success Tests

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_success_returns_success_true(self, mock_post, twilio_client):
        """Test that send_sms returns success=True on successful API call."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "sid": "SM123456789",
            "status": "queued"
        }
        mock_post.return_value = mock_response

        # Act
        result = twilio_client.send_sms(
            to="+15551234567",
            from_="+15559876543",
            body="Test message"
        )

        # Assert
        assert result["success"] is True
        assert result["message_sid"] == "SM123456789"
        assert result["error"] is None

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_success_with_200_status(self, mock_post, twilio_client):
        """Test that send_sms handles 200 status code as success."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"sid": "SM987654321"}
        mock_post.return_value = mock_response

        # Act
        result = twilio_client.send_sms(
            to="+15551234567",
            from_="+15559876543",
            body="Test message"
        )

        # Assert
        assert result["success"] is True
        assert result["message_sid"] == "SM987654321"

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_makes_correct_api_call(self, mock_post, twilio_client):
        """Test that send_sms makes the correct HTTP POST request."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"sid": "SM123456789"}
        mock_post.return_value = mock_response

        # Act
        twilio_client.send_sms(
            to="+15551234567",
            from_="+15559876543",
            body="Hello World"
        )

        # Assert
        mock_post.assert_called_once()
        call_args = mock_post.call_args

        # Verify URL
        assert call_args[0][0] == "https://api.twilio.com/2010-04-01/Accounts/AC123456789/Messages.json"

        # Verify headers
        assert "Authorization" in call_args.kwargs["headers"]
        assert call_args.kwargs["headers"]["Authorization"].startswith("Basic ")
        assert call_args.kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"

        # Verify data
        assert call_args.kwargs["data"]["To"] == "+15551234567"
        assert call_args.kwargs["data"]["From"] == "+15559876543"
        assert call_args.kwargs["data"]["Body"] == "Hello World"

        # Verify timeout
        assert call_args.kwargs["timeout"] == 10

    # Send SMS Error Tests

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_handles_400_error(self, mock_post, twilio_client):
        """Test that send_sms handles 400 error from Twilio API."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Invalid phone number"
        mock_post.return_value = mock_response

        # Act
        result = twilio_client.send_sms(
            to="invalid",
            from_="+15559876543",
            body="Test"
        )

        # Assert
        assert result["success"] is False
        assert result["message_sid"] is None
        assert "400" in result["error"]
        assert "Invalid phone number" in result["error"]

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_handles_401_unauthorized(self, mock_post, twilio_client):
        """Test that send_sms handles 401 unauthorized error."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_post.return_value = mock_response

        # Act
        result = twilio_client.send_sms(
            to="+15551234567",
            from_="+15559876543",
            body="Test"
        )

        # Assert
        assert result["success"] is False
        assert result["message_sid"] is None
        assert "401" in result["error"]

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_handles_500_server_error(self, mock_post, twilio_client):
        """Test that send_sms handles 500 server error."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        # Act
        result = twilio_client.send_sms(
            to="+15551234567",
            from_="+15559876543",
            body="Test"
        )

        # Assert
        assert result["success"] is False
        assert result["message_sid"] is None
        assert "500" in result["error"]

    # Timeout and Exception Tests

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_handles_timeout(self, mock_post, twilio_client):
        """Test that send_sms handles request timeout."""
        # Arrange
        mock_post.side_effect = requests.exceptions.Timeout()

        # Act
        result = twilio_client.send_sms(
            to="+15551234567",
            from_="+15559876543",
            body="Test"
        )

        # Assert
        assert result["success"] is False
        assert result["message_sid"] is None
        assert "timed out" in result["error"].lower()

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_handles_connection_error(self, mock_post, twilio_client):
        """Test that send_sms handles connection errors."""
        # Arrange
        mock_post.side_effect = requests.exceptions.ConnectionError("Failed to connect")

        # Act
        result = twilio_client.send_sms(
            to="+15551234567",
            from_="+15559876543",
            body="Test"
        )

        # Assert
        assert result["success"] is False
        assert result["message_sid"] is None
        assert "request failed" in result["error"].lower()
        assert "Failed to connect" in result["error"]

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_handles_generic_request_exception(self, mock_post, twilio_client):
        """Test that send_sms handles generic request exceptions."""
        # Arrange
        mock_post.side_effect = requests.exceptions.RequestException("Generic error")

        # Act
        result = twilio_client.send_sms(
            to="+15551234567",
            from_="+15559876543",
            body="Test"
        )

        # Assert
        assert result["success"] is False
        assert result["message_sid"] is None
        assert "request failed" in result["error"].lower()

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_handles_unexpected_exception(self, mock_post, twilio_client):
        """Test that send_sms handles unexpected exceptions."""
        # Arrange
        mock_post.side_effect = ValueError("Unexpected error")

        # Act
        result = twilio_client.send_sms(
            to="+15551234567",
            from_="+15559876543",
            body="Test"
        )

        # Assert
        assert result["success"] is False
        assert result["message_sid"] is None
        assert "unexpected error" in result["error"].lower()
        assert "Unexpected error" in result["error"]

    # Edge Case Tests

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_with_long_message_body(self, mock_post, twilio_client):
        """Test that send_sms handles long message bodies."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"sid": "SM123456789"}
        mock_post.return_value = mock_response

        long_message = "A" * 1600  # Max Twilio message length

        # Act
        result = twilio_client.send_sms(
            to="+15551234567",
            from_="+15559876543",
            body=long_message
        )

        # Assert
        assert result["success"] is True
        assert mock_post.call_args.kwargs["data"]["Body"] == long_message

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_with_special_characters(self, mock_post, twilio_client):
        """Test that send_sms handles special characters in message body."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"sid": "SM123456789"}
        mock_post.return_value = mock_response

        special_message = "Hello! 🎉 Test message with émojis & spëcial çhars"

        # Act
        result = twilio_client.send_sms(
            to="+15551234567",
            from_="+15559876543",
            body=special_message
        )

        # Assert
        assert result["success"] is True

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_response_missing_sid(self, mock_post, twilio_client):
        """Test that send_sms handles response missing 'sid' field."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"status": "queued"}  # No 'sid' field
        mock_post.return_value = mock_response

        # Act
        result = twilio_client.send_sms(
            to="+15551234567",
            from_="+15559876543",
            body="Test"
        )

        # Assert
        assert result["success"] is True
        assert result["message_sid"] is None  # Should handle missing sid gracefully
