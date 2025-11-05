from unittest.mock import MagicMock, patch

import pytest

from intake_agent.agent import (
    generate_verification_code,
    get_collected_data_summary,
    process_patient_message,
    send_verification_code,
)


class TestPhoneVerification:
    """Unit tests for phone verification functionality."""

    # Verification Code Generation Tests

    def test_generate_verification_code_returns_6_digits(self):
        """Test that generate_verification_code returns a 6-digit string."""
        # Act
        code = generate_verification_code()

        # Assert
        assert isinstance(code, str)
        assert len(code) == 6
        assert code.isdigit()

    def test_generate_verification_code_is_different(self):
        """Test that generate_verification_code generates different codes."""
        # Act
        code1 = generate_verification_code()
        code2 = generate_verification_code()

        # Assert (highly unlikely to be the same)
        # We'll generate multiple to reduce flakiness
        codes = [generate_verification_code() for _ in range(10)]
        assert len(set(codes)) > 1  # At least some variation

    # Send Verification Code Tests

    @patch("intake_agent.agent.TwilioClient")
    def test_send_verification_code_success(self, mock_twilio_class):
        """Test that send_verification_code successfully sends SMS."""
        # Arrange
        mock_client = MagicMock()
        mock_twilio_class.return_value = mock_client
        mock_client.send_sms.return_value = {
            "success": True,
            "message_sid": "SM123456",
            "error": None,
        }

        # Act
        result = send_verification_code(
            phone="+15551234567",
            code="123456",
            twilio_account_sid="AC123",
            twilio_auth_token="secret",
            twilio_phone_number="+15559876543",
        )

        # Assert
        assert result["success"] is True
        assert result["error"] is None
        mock_twilio_class.assert_called_once_with(account_sid="AC123", auth_token="secret")
        mock_client.send_sms.assert_called_once()

        # Verify SMS content
        call_args = mock_client.send_sms.call_args
        assert call_args.kwargs["to"] == "+15551234567"
        assert call_args.kwargs["from_"] == "+15559876543"
        assert "123456" in call_args.kwargs["body"]

    @patch("intake_agent.agent.TwilioClient")
    def test_send_verification_code_failure(self, mock_twilio_class):
        """Test that send_verification_code handles SMS failures."""
        # Arrange
        mock_client = MagicMock()
        mock_twilio_class.return_value = mock_client
        mock_client.send_sms.return_value = {
            "success": False,
            "message_sid": None,
            "error": "Invalid phone number",
        }

        # Act
        result = send_verification_code(
            phone="+15551234567",
            code="123456",
            twilio_account_sid="AC123",
            twilio_auth_token="secret",
            twilio_phone_number="+15559876543",
        )

        # Assert
        assert result["success"] is False
        assert "Invalid phone number" in result["error"]

    @patch("intake_agent.agent.TwilioClient")
    def test_send_verification_code_exception(self, mock_twilio_class):
        """Test that send_verification_code handles exceptions."""
        # Arrange
        mock_twilio_class.side_effect = Exception("Connection error")

        # Act
        result = send_verification_code(
            phone="+15551234567",
            code="123456",
            twilio_account_sid="AC123",
            twilio_auth_token="secret",
            twilio_phone_number="+15559876543",
        )

        # Assert
        assert result["success"] is False
        assert "Connection error" in result["error"]

    # Collected Data Summary Tests with Phone Verification

    def test_get_collected_data_summary_phone_not_verified(self):
        """Test that get_collected_data_summary shows phone as not verified."""
        # Arrange
        session_data = {
            "collected_data": {
                "first_name": "John",
                "last_name": None,
                "email": None,
                "phone": "+15551234567",
                "date_of_birth": None,
                "reason_for_visit": None,
            },
            "phone_verified": False,
            "phone_verification_code": None,
        }

        # Act
        result = get_collected_data_summary(session_data)

        # Assert
        assert "phone: '+15551234567' (NOT VERIFIED YET)" in result

    def test_get_collected_data_summary_phone_verified(self):
        """Test that get_collected_data_summary shows phone as verified."""
        # Arrange
        session_data = {
            "collected_data": {
                "first_name": "John",
                "last_name": None,
                "email": None,
                "phone": "+15551234567",
                "date_of_birth": None,
                "reason_for_visit": None,
            },
            "phone_verified": True,
            "phone_verification_code": "123456",
        }

        # Act
        result = get_collected_data_summary(session_data)

        # Assert
        assert "phone: '+15551234567' (VERIFIED)" in result

    def test_get_collected_data_summary_verification_code_sent(self):
        """Test that get_collected_data_summary shows verification code sent but NOT the actual code."""
        # Arrange
        session_data = {
            "collected_data": {
                "first_name": "John",
                "last_name": None,
                "email": None,
                "phone": "+15559999999",  # Changed to avoid false positive
                "date_of_birth": None,
                "reason_for_visit": None,
            },
            "phone_verified": False,
            "phone_verification_code": "123456",
        }

        # Act
        result = get_collected_data_summary(session_data)

        # Assert
        assert "phone: '+15559999999' (VERIFICATION CODE SENT, AWAITING PATIENT CONFIRMATION)" in result
        # SECURITY: Ensure the actual code is NOT revealed in the summary
        assert "123456" not in result
        # Also ensure we're not saying "CODE: 123456" or similar
        assert "CODE SENT: " not in result
        assert ": 123456" not in result

    # Process Patient Message Tests with Phone Verification

    @patch("intake_agent.agent.send_verification_code")
    @patch("intake_agent.agent.generate_verification_code")
    @patch("intake_agent.agent.update_session")
    @patch("intake_agent.agent.LlmAnthropic")
    @patch("intake_agent.agent.get_session")
    def test_process_patient_message_sends_verification_code(
        self,
        mock_get_session,
        mock_llm_class,
        mock_update_session,
        mock_generate_code,
        mock_send_code,
    ):
        """Test that process_patient_message sends verification code when requested."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "status": "active",
            "messages": [],
            "collected_data": {
                "first_name": None,
                "last_name": None,
                "email": None,
                "phone": "+15551234567",
                "date_of_birth": None,
                "reason_for_visit": None,
            },
            "phone_verified": False,
            "phone_verification_code": None,
        }

        mock_generate_code.return_value = "123456"
        mock_send_code.return_value = {"success": True, "error": None}

        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm
        mock_llm.chat_with_json.return_value = {
            "success": True,
            "data": {
                "extracted_data": {
                    "first_name": None,
                    "last_name": None,
                    "email": None,
                    "phone": "+15551234567",
                    "date_of_birth": None,
                    "reason_for_visit": None,
                },
                "send_verification_code": True,
                "verification_code_match": None,
                "all_information_collected": False,
                "response_to_patient": "I've sent a verification code to your phone.",
            },
        }

        # Act
        result = process_patient_message(
            "test-session",
            "My phone is +15551234567",
            "test-api-key",
            "AC123",
            "secret",
            "+15559876543",
        )

        # Assert
        assert isinstance(result, dict)
        assert "sent a verification code" in result["response"]
        mock_generate_code.assert_called_once()
        mock_send_code.assert_called_once_with(
            phone="+15551234567",
            code="123456",
            twilio_account_sid="AC123",
            twilio_auth_token="secret",
            twilio_phone_number="+15559876543",
        )

    @patch("intake_agent.agent.update_session")
    @patch("intake_agent.agent.LlmAnthropic")
    @patch("intake_agent.agent.get_session")
    def test_process_patient_message_verifies_correct_code(
        self, mock_get_session, mock_llm_class, mock_update_session
    ):
        """Test that process_patient_message verifies matching code."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "status": "active",
            "messages": [],
            "collected_data": {
                "first_name": None,
                "last_name": None,
                "email": None,
                "phone": "+15551234567",
                "date_of_birth": None,
                "reason_for_visit": None,
            },
            "phone_verified": False,
            "phone_verification_code": "123456",
        }

        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm
        mock_llm.chat_with_json.return_value = {
            "success": True,
            "data": {
                "extracted_data": {},
                "send_verification_code": False,
                "verification_code_match": True,
                "all_information_collected": False,
                "response_to_patient": "Great! Your phone number is verified.",
            },
        }

        # Act
        result = process_patient_message(
            "test-session", "The code is 123456", "test-api-key"
        )

        # Assert
        assert isinstance(result, dict)
        assert "verified" in result["response"].lower()

        # Verify that phone_verified was set to True
        update_calls = mock_update_session.call_args_list
        assert len(update_calls) >= 1
        # Check that at least one call has phone_verified=True
        verified_call_found = False
        for call in update_calls:
            session_data = call[0][1]  # Second argument (session_data)
            if session_data.get("phone_verified") is True:
                verified_call_found = True
                break
        assert verified_call_found

    @patch("intake_agent.agent.update_session")
    @patch("intake_agent.agent.LlmAnthropic")
    @patch("intake_agent.agent.get_session")
    def test_process_patient_message_rejects_incorrect_code(
        self, mock_get_session, mock_llm_class, mock_update_session
    ):
        """Test that process_patient_message handles incorrect code."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "status": "active",
            "messages": [],
            "collected_data": {
                "first_name": None,
                "last_name": None,
                "email": None,
                "phone": "+15551234567",
                "date_of_birth": None,
                "reason_for_visit": None,
            },
            "phone_verified": False,
            "phone_verification_code": "123456",
        }

        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm
        mock_llm.chat_with_json.return_value = {
            "success": True,
            "data": {
                "extracted_data": {},
                "send_verification_code": False,
                "verification_code_match": False,
                "all_information_collected": False,
                "response_to_patient": "That code doesn't match. Please try again.",
            },
        }

        # Act
        result = process_patient_message(
            "test-session", "The code is 999999", "test-api-key"
        )

        # Assert
        assert isinstance(result, dict)
        assert "doesn't match" in result["response"]

    @patch("intake_agent.agent.complete_session")
    @patch("intake_agent.agent.update_session")
    @patch("intake_agent.agent.LlmAnthropic")
    @patch("intake_agent.agent.get_session")
    def test_process_patient_message_requires_verification_before_completion(
        self, mock_get_session, mock_llm_class, mock_update_session, mock_complete_session
    ):
        """Test that process_patient_message doesn't complete without phone verification."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "status": "active",
            "messages": [],
            "collected_data": {
                "first_name": "John",
                "last_name": "Doe",
                "email": "john@example.com",
                "phone": "+15551234567",
                "date_of_birth": "1990-01-01",
                "reason_for_visit": "Annual checkup",
            },
            "phone_verified": False,
            "phone_verification_code": "123456",
        }

        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm
        mock_llm.chat_with_json.return_value = {
            "success": True,
            "data": {
                "extracted_data": {},
                "send_verification_code": False,
                "verification_code_match": None,
                "all_information_collected": True,
                "response_to_patient": "Please verify your phone first.",
            },
        }

        # Act
        result = process_patient_message(
            "test-session", "I'm ready", "test-api-key"
        )

        # Assert
        assert isinstance(result, dict)
        assert result["effects"] == []  # No patient creation
        mock_complete_session.assert_not_called()  # Session not completed
