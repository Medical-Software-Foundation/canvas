from unittest.mock import MagicMock, patch

import pytest

from intake_agent.twilio_client import TwilioClient


class TestTwilioClient:
    """Unit tests for TwilioClient."""

    def test_initialization(self):
        """Test that TwilioClient initializes correctly."""
        # Arrange & Act
        client = TwilioClient(account_sid="AC123456", auth_token="secret123")

        # Assert
        assert client.account_sid == "AC123456"
        assert client.auth_token == "secret123"
        assert client.base_url == "https://api.twilio.com/2010-04-01/Accounts/AC123456"

    def test_get_auth_header(self):
        """Test that _get_auth_header generates correct Basic Auth header."""
        # Arrange
        client = TwilioClient(account_sid="AC123456", auth_token="secret123")

        # Act
        auth_header = client._get_auth_header()

        # Assert
        assert auth_header.startswith("Basic ")
        # Verify it's base64 encoded (should contain AC123456:secret123)
        import base64

        decoded = base64.b64decode(auth_header.replace("Basic ", "")).decode()
        assert decoded == "AC123456:secret123"

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_success(self, mock_post):
        """Test that send_sms successfully sends a message."""
        # Arrange
        client = TwilioClient(account_sid="AC123456", auth_token="secret123")

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"sid": "SM123456789"}
        mock_post.return_value = mock_response

        # Act
        result = client.send_sms(to="+15551234567", from_="+15559876543", body="Test message")

        # Assert
        assert result["success"] is True
        assert result["message_sid"] == "SM123456789"
        assert result["error"] is None
        mock_post.assert_called_once()

        # Verify request parameters
        call_args = mock_post.call_args
        assert call_args.kwargs["data"]["To"] == "+15551234567"
        assert call_args.kwargs["data"]["From"] == "+15559876543"
        assert call_args.kwargs["data"]["Body"] == "Test message"

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_api_error(self, mock_post):
        """Test that send_sms handles API errors."""
        # Arrange
        client = TwilioClient(account_sid="AC123456", auth_token="secret123")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Invalid phone number"
        mock_post.return_value = mock_response

        # Act
        result = client.send_sms(to="+15551234567", from_="+15559876543", body="Test message")

        # Assert
        assert result["success"] is False
        assert result["message_sid"] is None
        assert "400" in result["error"]
        assert "Invalid phone number" in result["error"]

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_timeout(self, mock_post):
        """Test that send_sms handles timeout errors."""
        # Arrange
        client = TwilioClient(account_sid="AC123456", auth_token="secret123")

        import requests

        mock_post.side_effect = requests.exceptions.Timeout()

        # Act
        result = client.send_sms(to="+15551234567", from_="+15559876543", body="Test message")

        # Assert
        assert result["success"] is False
        assert result["message_sid"] is None
        assert "timed out" in result["error"].lower()

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_request_exception(self, mock_post):
        """Test that send_sms handles request exceptions."""
        # Arrange
        client = TwilioClient(account_sid="AC123456", auth_token="secret123")

        import requests

        mock_post.side_effect = requests.exceptions.RequestException("Connection error")

        # Act
        result = client.send_sms(to="+15551234567", from_="+15559876543", body="Test message")

        # Assert
        assert result["success"] is False
        assert result["message_sid"] is None
        assert "Connection error" in result["error"]

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_unexpected_exception(self, mock_post):
        """Test that send_sms handles unexpected exceptions."""
        # Arrange
        client = TwilioClient(account_sid="AC123456", auth_token="secret123")

        mock_post.side_effect = Exception("Unexpected error")

        # Act
        result = client.send_sms(to="+15551234567", from_="+15559876543", body="Test message")

        # Assert
        assert result["success"] is False
        assert result["message_sid"] is None
        assert "Unexpected error" in result["error"]

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_uses_correct_url(self, mock_post):
        """Test that send_sms uses the correct Twilio API URL."""
        # Arrange
        client = TwilioClient(account_sid="AC123456", auth_token="secret123")

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"sid": "SM123456789"}
        mock_post.return_value = mock_response

        # Act
        client.send_sms(to="+15551234567", from_="+15559876543", body="Test message")

        # Assert
        expected_url = "https://api.twilio.com/2010-04-01/Accounts/AC123456/Messages.json"
        call_args = mock_post.call_args
        assert call_args.args[0] == expected_url

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_includes_auth_header(self, mock_post):
        """Test that send_sms includes authorization header."""
        # Arrange
        client = TwilioClient(account_sid="AC123456", auth_token="secret123")

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"sid": "SM123456789"}
        mock_post.return_value = mock_response

        # Act
        client.send_sms(to="+15551234567", from_="+15559876543", body="Test message")

        # Assert
        call_args = mock_post.call_args
        headers = call_args.kwargs["headers"]
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic ")

    @patch("intake_agent.twilio_client.requests.post")
    def test_send_sms_sets_timeout(self, mock_post):
        """Test that send_sms sets a timeout for the request."""
        # Arrange
        client = TwilioClient(account_sid="AC123456", auth_token="secret123")

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"sid": "SM123456789"}
        mock_post.return_value = mock_response

        # Act
        client.send_sms(to="+15551234567", from_="+15559876543", body="Test message")

        # Assert
        call_args = mock_post.call_args
        assert call_args.kwargs["timeout"] == 10
