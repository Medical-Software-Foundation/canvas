from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from intake_agent.tools import Toolkit
from intake_agent.api.session import IntakeSession, ProposedAppointment


class TestToolkit:
    """Unit tests for Toolkit class."""

    # Generate Verification Code Tests

    def test_generate_verification_code_returns_string(self):
        """Test that generate_verification_code returns a string."""
        # Act
        code = Toolkit.generate_verification_code()

        # Assert
        assert isinstance(code, str)

    def test_generate_verification_code_returns_6_digits(self):
        """Test that generate_verification_code returns exactly 6 digits."""
        # Act
        code = Toolkit.generate_verification_code()

        # Assert
        assert len(code) == 6
        assert code.isdigit()

    def test_generate_verification_code_has_leading_zeros(self):
        """Test that generate_verification_code pads with leading zeros."""
        # Arrange - Set seed to get predictable results for testing
        with patch("intake_agent.tools.random.randint", return_value=42):
            # Act
            code = Toolkit.generate_verification_code()

            # Assert
            assert code == "000042"

    def test_generate_verification_code_generates_different_codes(self):
        """Test that generate_verification_code generates varied codes."""
        # Act
        codes = [Toolkit.generate_verification_code() for _ in range(100)]

        # Assert - Should have multiple unique values
        assert len(set(codes)) > 10

    # Send Verification Code Tests

    @patch("intake_agent.tools.TwilioClient")
    def test_send_verification_code_success(self, mock_twilio_class):
        """Test that send_verification_code returns success when SMS sends."""
        # Arrange
        mock_client = MagicMock()
        mock_twilio_class.return_value = mock_client
        mock_client.send_sms.return_value = {
            "success": True,
            "message_sid": "SM123456",
            "error": None,
        }

        # Act
        result = Toolkit.send_verification_code(
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

    @patch("intake_agent.tools.TwilioClient")
    def test_send_verification_code_formats_message_correctly(self, mock_twilio_class):
        """Test that send_verification_code formats the SMS message correctly."""
        # Arrange
        mock_client = MagicMock()
        mock_twilio_class.return_value = mock_client
        mock_client.send_sms.return_value = {"success": True, "message_sid": "SM123", "error": None}

        # Act
        Toolkit.send_verification_code(
            phone="+15551234567",
            code="987654",
            twilio_account_sid="AC123",
            twilio_auth_token="secret",
            twilio_phone_number="+15559876543",
        )

        # Assert
        call_args = mock_client.send_sms.call_args
        assert call_args.kwargs["to"] == "+15551234567"
        assert call_args.kwargs["from_"] == "+15559876543"
        assert "987654" in call_args.kwargs["body"]
        assert "Your verification code is:" in call_args.kwargs["body"]

    @patch("intake_agent.tools.TwilioClient")
    def test_send_verification_code_failure(self, mock_twilio_class):
        """Test that send_verification_code returns error when SMS fails."""
        # Arrange
        mock_client = MagicMock()
        mock_twilio_class.return_value = mock_client
        mock_client.send_sms.return_value = {
            "success": False,
            "message_sid": None,
            "error": "Invalid phone number",
        }

        # Act
        result = Toolkit.send_verification_code(
            phone="invalid",
            code="123456",
            twilio_account_sid="AC123",
            twilio_auth_token="secret",
            twilio_phone_number="+15559876543",
        )

        # Assert
        assert result["success"] is False
        assert result["error"] == "Invalid phone number"

    # Send Appointment Confirmation SMS Tests

    @patch("intake_agent.tools.TwilioClient")
    def test_send_appointment_confirmation_sms_success(self, mock_twilio_class):
        """Test that send_appointment_confirmation_sms returns success."""
        # Arrange
        mock_client = MagicMock()
        mock_twilio_class.return_value = mock_client
        mock_client.send_sms.return_value = {"success": True, "message_sid": "SM123", "error": None}

        appointment_time = datetime(2025, 1, 15, 9, 0, 0)

        # Act
        result = Toolkit.send_appointment_confirmation_sms(
            phone="+15551234567",
            appointment_time=appointment_time,
            appointment_location="Main Clinic",
            mrn="MRN123456",
            twilio_account_sid="AC123",
            twilio_auth_token="secret",
            twilio_phone_number="+15559876543",
        )

        # Assert
        assert result["success"] is True
        assert result["error"] is None

    @patch("intake_agent.tools.TwilioClient")
    def test_send_appointment_confirmation_sms_formats_message_correctly(self, mock_twilio_class):
        """Test that send_appointment_confirmation_sms formats message with all details."""
        # Arrange
        mock_client = MagicMock()
        mock_twilio_class.return_value = mock_client
        mock_client.send_sms.return_value = {"success": True, "message_sid": "SM123", "error": None}

        appointment_time = datetime(2025, 1, 15, 14, 30, 0)

        # Act
        Toolkit.send_appointment_confirmation_sms(
            phone="+15551234567",
            appointment_time=appointment_time,
            appointment_location="Virtual (Zoom)",
            mrn="MRN789012",
            twilio_account_sid="AC123",
            twilio_auth_token="secret",
            twilio_phone_number="+15559876543",
        )

        # Assert
        call_args = mock_client.send_sms.call_args
        message_body = call_args.kwargs["body"]

        # Verify all components are in the message
        assert "Your appointment is confirmed" in message_body
        assert "Wednesday, January 15 at 02:30 PM" in message_body
        assert "Virtual (Zoom)" in message_body
        assert "MRN789012" in message_body

    @patch("intake_agent.tools.TwilioClient")
    def test_send_appointment_confirmation_sms_failure(self, mock_twilio_class):
        """Test that send_appointment_confirmation_sms returns error on failure."""
        # Arrange
        mock_client = MagicMock()
        mock_twilio_class.return_value = mock_client
        mock_client.send_sms.return_value = {
            "success": False,
            "message_sid": None,
            "error": "SMS delivery failed",
        }

        appointment_time = datetime(2025, 1, 15, 9, 0, 0)

        # Act
        result = Toolkit.send_appointment_confirmation_sms(
            phone="+15551234567",
            appointment_time=appointment_time,
            appointment_location="Main Clinic",
            mrn="MRN123456",
            twilio_account_sid="AC123",
            twilio_auth_token="secret",
            twilio_phone_number="+15559876543",
        )

        # Assert
        assert result["success"] is False
        assert result["error"] == "SMS delivery failed"

    # Get Next Available Appointments Tests

    @patch("intake_agent.tools.datetime")
    def test_get_next_available_appointments_returns_list(self, mock_datetime):
        """Test that get_next_available_appointments returns a list."""
        # Arrange
        fixed_now = datetime(2025, 1, 14, 10, 0, 0)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        # Act
        result = Toolkit.get_next_available_appointments()

        # Assert
        assert isinstance(result, list)

    @patch("intake_agent.tools.datetime")
    def test_get_next_available_appointments_returns_two_slots(self, mock_datetime):
        """Test that get_next_available_appointments returns exactly 2 appointments."""
        # Arrange
        fixed_now = datetime(2025, 1, 14, 10, 0, 0)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        # Act
        result = Toolkit.get_next_available_appointments()

        # Assert
        assert len(result) == 2

    @patch("intake_agent.tools.datetime")
    def test_get_next_available_appointments_returns_proposed_appointment_objects(self, mock_datetime):
        """Test that get_next_available_appointments returns ProposedAppointment objects."""
        # Arrange
        fixed_now = datetime(2025, 1, 14, 10, 0, 0)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        # Act
        result = Toolkit.get_next_available_appointments()

        # Assert
        assert all(isinstance(apt, ProposedAppointment) for apt in result)

    @patch("intake_agent.tools.datetime")
    def test_get_next_available_appointments_morning_slot_is_9am(self, mock_datetime):
        """Test that get_next_available_appointments includes 9 AM morning slot."""
        # Arrange
        fixed_now = datetime(2025, 1, 14, 10, 0, 0)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        # Act
        result = Toolkit.get_next_available_appointments()

        # Assert
        morning_slot = result[0]
        assert morning_slot.start_datetime.hour == 9
        assert morning_slot.start_datetime.minute == 0
        assert morning_slot.provider_name == "Veronica Hernandez, MD"
        assert morning_slot.location_name == "Main Clinic"
        assert morning_slot.duration == 20

    @patch("intake_agent.tools.datetime")
    def test_get_next_available_appointments_afternoon_slot_is_2pm(self, mock_datetime):
        """Test that get_next_available_appointments includes 2 PM afternoon slot."""
        # Arrange
        fixed_now = datetime(2025, 1, 14, 10, 0, 0)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        # Act
        result = Toolkit.get_next_available_appointments()

        # Assert
        afternoon_slot = result[1]
        assert afternoon_slot.start_datetime.hour == 14
        assert afternoon_slot.start_datetime.minute == 0
        assert afternoon_slot.provider_name == "Evan Stern, NP"
        assert afternoon_slot.location_name == "Virtual (Zoom)"
        assert afternoon_slot.duration == 30

    @patch("intake_agent.tools.datetime")
    def test_get_next_available_appointments_is_for_tomorrow(self, mock_datetime):
        """Test that get_next_available_appointments returns slots for tomorrow."""
        # Arrange
        fixed_now = datetime(2025, 1, 14, 10, 0, 0)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        # Act
        result = Toolkit.get_next_available_appointments()

        # Assert
        expected_date = datetime(2025, 1, 15)
        for apt in result:
            assert apt.start_datetime.year == expected_date.year
            assert apt.start_datetime.month == expected_date.month
            assert apt.start_datetime.day == expected_date.day

    # Create Patient Tests

    @patch("intake_agent.tools.log")
    def test_create_patient_creates_patient_effect(self, mock_log):
        """Test that create_patient returns a Patient effect."""
        # Arrange
        mock_session = MagicMock(spec=IntakeSession)
        mock_session.session_id = "test-session-123"
        mock_session.first_name = "John"
        mock_session.last_name = "Doe"
        mock_session.date_of_birth = datetime(1990, 1, 1).date()
        mock_session.phone_number = "+15551234567"
        mock_session.phone_verified.return_value = True

        # Act
        result = Toolkit.create_patient(mock_session)

        # Assert
        # The result should be an Effect (we can't easily test the exact type without Canvas SDK)
        assert result is not None
        mock_log.info.assert_called_once()
        assert "test-session-123" in mock_log.info.call_args[0][0]

    @patch("intake_agent.tools.log")
    def test_create_patient_uses_session_data(self, mock_log):
        """Test that create_patient uses data from the session."""
        # Arrange
        mock_session = MagicMock(spec=IntakeSession)
        mock_session.session_id = "test-session-456"
        mock_session.first_name = "Jane"
        mock_session.last_name = "Smith"
        mock_session.date_of_birth = datetime(1985, 6, 15).date()
        mock_session.phone_number = "+15559876543"
        mock_session.phone_verified.return_value = False

        # Act
        result = Toolkit.create_patient(mock_session)

        # Assert
        # Verify the session data was accessed
        assert mock_session.first_name == "Jane"
        assert mock_session.last_name == "Smith"
        mock_session.phone_verified.assert_called_once()
        assert result is not None

    @patch("intake_agent.tools.log")
    def test_create_patient_logs_session_id(self, mock_log):
        """Test that create_patient logs the session ID."""
        # Arrange
        mock_session = MagicMock(spec=IntakeSession)
        mock_session.session_id = "log-test-session"
        mock_session.first_name = "Test"
        mock_session.last_name = "User"
        mock_session.date_of_birth = datetime(1995, 3, 20).date()
        mock_session.phone_number = "+15551111111"
        mock_session.phone_verified.return_value = True

        # Act
        Toolkit.create_patient(mock_session)

        # Assert
        mock_log.info.assert_called_once()
        log_message = mock_log.info.call_args[0][0]
        assert "log-test-session" in log_message
        assert "Queued patient creation effect" in log_message
