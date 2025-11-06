from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from intake_agent.api.session import (
    IntakeMessage,
    ProposedAppointment,
    IntakeSession,
    IntakeSessionManager,
)


class TestIntakeMessage:
    """Unit tests for IntakeMessage class."""

    def test_to_dict_converts_to_dictionary(self):
        """Test that to_dict converts IntakeMessage to dict."""
        # Arrange
        timestamp = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        message = IntakeMessage(
            role="user",
            content="Hello",
            timestamp=timestamp
        )

        # Act
        result = message.to_dict()

        # Assert
        assert result["role"] == "user"
        assert result["content"] == "Hello"
        assert result["timestamp"] == "2025-01-15T10:30:00+00:00"

    def test_from_dict_creates_intake_message(self):
        """Test that from_dict creates IntakeMessage from dict."""
        # Arrange
        data = {
            "role": "agent",
            "content": "Hi there!",
            "timestamp": "2025-01-15T10:30:00+00:00"
        }

        # Act
        message = IntakeMessage.from_dict(data)

        # Assert
        assert message.role == "agent"
        assert message.content == "Hi there!"
        assert message.timestamp == datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_roundtrip_to_dict_and_from_dict(self):
        """Test that to_dict and from_dict are inverse operations."""
        # Arrange
        original = IntakeMessage(
            role="user",
            content="Test message",
            timestamp=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        )

        # Act
        roundtrip = IntakeMessage.from_dict(original.to_dict())

        # Assert
        assert roundtrip.role == original.role
        assert roundtrip.content == original.content
        assert roundtrip.timestamp == original.timestamp


class TestProposedAppointment:
    """Unit tests for ProposedAppointment class."""

    def test_to_dict_converts_to_dictionary(self):
        """Test that to_dict converts ProposedAppointment to dict."""
        # Arrange
        start_time = datetime(2025, 1, 16, 9, 0, 0)
        appointment = ProposedAppointment(
            provider_id="provider-1",
            provider_name="Dr. Smith",
            location_id="location-1",
            location_name="Main Clinic",
            start_datetime=start_time,
            duration=30
        )

        # Act
        result = appointment.to_dict()

        # Assert
        assert result["provider_id"] == "provider-1"
        assert result["provider_name"] == "Dr. Smith"
        assert result["location_id"] == "location-1"
        assert result["location_name"] == "Main Clinic"
        assert result["start_datetime"] == start_time
        assert result["duration"] == 30

    def test_from_dict_creates_proposed_appointment(self):
        """Test that from_dict creates ProposedAppointment from dict."""
        # Arrange
        start_time = datetime(2025, 1, 16, 14, 0, 0)
        data = {
            "provider_id": "provider-2",
            "provider_name": "Dr. Jones",
            "location_id": "location-2",
            "location_name": "Virtual",
            "start_datetime": start_time,
            "duration": 20
        }

        # Act
        appointment = ProposedAppointment.from_dict(data)

        # Assert
        assert appointment.provider_id == "provider-2"
        assert appointment.provider_name == "Dr. Jones"
        assert appointment.location_id == "location-2"
        assert appointment.location_name == "Virtual"
        assert appointment.start_datetime == start_time
        assert appointment.duration == 20

    def test_to_string_formats_appointment_naturally(self):
        """Test that to_string formats appointment in patient-friendly way."""
        # Arrange
        start_time = datetime(2025, 1, 16, 9, 30, 0)
        appointment = ProposedAppointment(
            provider_id="provider-1",
            provider_name="Dr. Smith",
            location_id="location-1",
            location_name="Main Clinic",
            start_datetime=start_time,
            duration=30
        )

        # Act
        result = appointment.to_string()

        # Assert
        assert "Thursday, January 16" in result
        assert "9:30 AM" in result
        assert "Dr. Smith" in result
        assert "Main Clinic" in result
        assert "provider-1" not in result  # Should not include IDs
        assert "location-1" not in result

    def test_to_string_strips_leading_zero_from_time(self):
        """Test that to_string strips leading zero from single-digit hours."""
        # Arrange
        start_time = datetime(2025, 1, 16, 9, 0, 0)
        appointment = ProposedAppointment(
            provider_id="provider-1",
            provider_name="Dr. Smith",
            location_id="location-1",
            location_name="Main Clinic",
            start_datetime=start_time,
            duration=30
        )

        # Act
        result = appointment.to_string()

        # Assert
        assert "9:00 AM" in result  # Not "09:00 AM"


class TestIntakeSession:
    """Unit tests for IntakeSession class."""

    @pytest.fixture
    def basic_session(self):
        """Create a basic IntakeSession for testing."""
        return IntakeSession(
            session_id="test-session-123",
            created_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        )

    # Save Tests

    @patch("intake_agent.api.session.get_cache")
    def test_save_stores_session_in_cache(self, mock_get_cache, basic_session):
        """Test that save stores the session in cache."""
        # Arrange
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache

        # Act
        basic_session.save()

        # Assert
        mock_cache.set.assert_called_once()
        call_args = mock_cache.set.call_args
        assert call_args[0][0] == "intake_session:test-session-123"
        assert isinstance(call_args[0][1], dict)

    # Add Message Tests

    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.api.session.log")
    def test_add_message_appends_to_messages(self, mock_log, mock_get_cache, basic_session):
        """Test that add_message appends message to the list."""
        # Arrange
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache

        # Act
        basic_session.add_message("user", "Hello")

        # Assert
        assert len(basic_session.messages) == 1
        assert basic_session.messages[0].role == "user"
        assert basic_session.messages[0].content == "Hello"

    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.api.session.log")
    def test_add_message_saves_session(self, mock_log, mock_get_cache, basic_session):
        """Test that add_message calls save."""
        # Arrange
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache

        # Act
        basic_session.add_message("agent", "Hi there")

        # Assert
        mock_cache.set.assert_called_once()

    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.api.session.log")
    def test_add_message_logs_message(self, mock_log, mock_get_cache, basic_session):
        """Test that add_message logs the message."""
        # Arrange
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache

        # Act
        basic_session.add_message("user", "Test message")

        # Assert
        mock_log.info.assert_called_once()
        log_message = mock_log.info.call_args[0][0]
        assert "user" in log_message
        assert "Test message" in log_message

    # Internal Fields Tests

    def test_internal_fields_returns_list(self, basic_session):
        """Test that internal_fields returns a list."""
        # Act
        result = basic_session.internal_fields()

        # Assert
        assert isinstance(result, list)

    def test_internal_fields_includes_session_id(self, basic_session):
        """Test that internal_fields includes session_id."""
        # Act
        result = basic_session.internal_fields()

        # Assert
        assert "session_id" in result

    def test_internal_fields_includes_expected_fields(self, basic_session):
        """Test that internal_fields includes all expected internal fields."""
        # Act
        result = basic_session.internal_fields()

        # Assert
        expected = [
            "session_id",
            "created_at",
            "patient_creation_pending",
            "patient_id",
            "patient_mrn",
            "phone_verification_code",
            "proposed_appointments",
            "appointment_confirmation_timestamp",
            "messages"
        ]
        for field in expected:
            assert field in result

    # Target Fields Remaining Tests

    def test_target_fields_remaining_returns_all_when_empty(self, basic_session):
        """Test that target_fields_remaining returns all groups when session is empty."""
        # Act
        result = basic_session.target_fields_remaining()

        # Assert
        assert len(result) > 0
        assert ["health_concerns"] in result
        assert ["phone_number"] in result

    def test_target_fields_remaining_excludes_filled_fields(self):
        """Test that target_fields_remaining excludes fields that are filled."""
        # Arrange
        session = IntakeSession(
            session_id="test-session",
            created_at=datetime.now(timezone.utc),
            health_concerns="Back pain",
            phone_number="+15551234567"
        )

        # Act
        result = session.target_fields_remaining()

        # Assert
        # health_concerns should not be in remaining
        assert ["health_concerns"] not in result
        # phone_number should not be in remaining
        assert ["phone_number"] not in result

    def test_target_fields_remaining_includes_name_dob_group(self, basic_session):
        """Test that target_fields_remaining includes name/dob as a group."""
        # Act
        result = basic_session.target_fields_remaining()

        # Assert
        name_dob_group = ["first_name", "last_name", "date_of_birth"]
        assert name_dob_group in result

    # Patient Exists Tests

    def test_patient_exists_returns_false_when_no_patient_id(self, basic_session):
        """Test that patient_exists returns False when patient_id is empty."""
        # Act
        result = basic_session.patient_exists()

        # Assert
        assert result is False

    def test_patient_exists_returns_true_when_patient_id_set(self):
        """Test that patient_exists returns True when patient_id is set."""
        # Arrange
        session = IntakeSession(
            session_id="test-session",
            created_at=datetime.now(timezone.utc),
            patient_id="patient-123"
        )

        # Act
        result = session.patient_exists()

        # Assert
        assert result is True

    # Phone Verified Tests

    def test_phone_verified_returns_false_when_codes_dont_match(self, basic_session):
        """Test that phone_verified returns False when codes don't match."""
        # Arrange
        session = basic_session._replace(
            phone_verification_code="123456",
            user_submitted_phone_verified_code="654321"
        )

        # Act
        result = session.phone_verified()

        # Assert
        assert result is False

    def test_phone_verified_returns_true_when_codes_match(self):
        """Test that phone_verified returns True when codes match."""
        # Arrange
        session = IntakeSession(
            session_id="test-session",
            created_at=datetime.now(timezone.utc),
            phone_verification_code="123456",
            user_submitted_phone_verified_code="123456"
        )

        # Act
        result = session.phone_verified()

        # Assert
        assert result is True

    # Sufficient Data to Create Patient Tests

    def test_sufficient_data_to_create_patient_returns_false_when_missing_data(self, basic_session):
        """Test that sufficient_data_to_create_patient returns False when data missing."""
        # Act
        result = basic_session.sufficient_data_to_create_patient()

        # Assert
        assert not result  # Should be falsy (empty string counts as False)

    def test_sufficient_data_to_create_patient_returns_false_when_phone_not_verified(self):
        """Test that sufficient_data_to_create_patient returns False when phone not verified."""
        # Arrange
        session = IntakeSession(
            session_id="test-session",
            created_at=datetime.now(timezone.utc),
            first_name="John",
            last_name="Doe",
            date_of_birth=datetime(1990, 1, 1).date(),
            phone_verification_code="123456",
            user_submitted_phone_verified_code="654321"  # Wrong code
        )

        # Act
        result = session.sufficient_data_to_create_patient()

        # Assert
        assert result is False

    def test_sufficient_data_to_create_patient_returns_true_when_all_present(self):
        """Test that sufficient_data_to_create_patient returns True when all data present."""
        # Arrange
        session = IntakeSession(
            session_id="test-session",
            created_at=datetime.now(timezone.utc),
            first_name="John",
            last_name="Doe",
            date_of_birth=datetime(1990, 1, 1).date(),
            phone_verification_code="123456",
            user_submitted_phone_verified_code="123456"  # Matching code
        )

        # Act
        result = session.sufficient_data_to_create_patient()

        # Assert
        assert result is True

    # To Dict Tests

    def test_to_dict_includes_all_fields(self, basic_session):
        """Test that to_dict includes all session fields."""
        # Act
        result = basic_session.to_dict()

        # Assert
        assert "session_id" in result
        assert "created_at" in result
        assert "first_name" in result
        assert "last_name" in result
        assert "phone_number" in result

    def test_to_dict_serializes_datetime_to_isoformat(self):
        """Test that to_dict converts datetime to ISO format string."""
        # Arrange
        session = IntakeSession(
            session_id="test-session",
            created_at=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        )

        # Act
        result = session.to_dict()

        # Assert
        assert result["created_at"] == "2025-01-15T10:30:00+00:00"

    def test_to_dict_handles_none_date_of_birth(self, basic_session):
        """Test that to_dict handles None date_of_birth."""
        # Act
        result = basic_session.to_dict()

        # Assert
        assert result["date_of_birth"] is None

    def test_to_dict_serializes_messages(self):
        """Test that to_dict serializes messages list."""
        # Arrange
        session = IntakeSession(
            session_id="test-session",
            created_at=datetime.now(timezone.utc),
            messages=[
                IntakeMessage("user", "Hello", datetime.now(timezone.utc)),
                IntakeMessage("agent", "Hi", datetime.now(timezone.utc))
            ]
        )

        # Act
        result = session.to_dict()

        # Assert
        assert len(result["messages"]) == 2
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][1]["role"] == "agent"

    # From Dict Tests

    def test_from_dict_creates_intake_session(self):
        """Test that from_dict creates IntakeSession from dict."""
        # Arrange
        data = {
            "session_id": "test-session-456",
            "created_at": "2025-01-15T10:00:00+00:00",
            "patient_creation_pending": False,
            "patient_id": "",
            "patient_mrn": "",
            "first_name": "Jane",
            "last_name": "Doe",
            "date_of_birth": None,
            "phone_number": "+15551234567",
            "phone_verification_code": "",
            "user_submitted_phone_verified_code": "",
            "health_concerns": "",
            "proposed_appointments": [],
            "preferred_appointment": None,
            "appointment_confirmation_timestamp": None,
            "policy_agreement_timestamp": None,
            "messages": []
        }

        # Act
        session = IntakeSession.from_dict(data)

        # Assert
        assert session.session_id == "test-session-456"
        assert session.first_name == "Jane"
        assert session.last_name == "Doe"
        assert session.phone_number == "+15551234567"

    def test_from_dict_handles_messages(self):
        """Test that from_dict deserializes messages."""
        # Arrange
        data = {
            "session_id": "test-session",
            "created_at": "2025-01-15T10:00:00+00:00",
            "patient_creation_pending": False,
            "patient_id": "",
            "patient_mrn": "",
            "first_name": "",
            "last_name": "",
            "date_of_birth": None,
            "phone_number": "",
            "phone_verification_code": "",
            "user_submitted_phone_verified_code": "",
            "health_concerns": "",
            "proposed_appointments": [],
            "preferred_appointment": None,
            "appointment_confirmation_timestamp": None,
            "policy_agreement_timestamp": None,
            "messages": [
                {"role": "user", "content": "Hello", "timestamp": "2025-01-15T10:00:00+00:00"}
            ]
        }

        # Act
        session = IntakeSession.from_dict(data)

        # Assert
        assert len(session.messages) == 1
        assert session.messages[0].role == "user"
        assert session.messages[0].content == "Hello"

    def test_roundtrip_to_dict_and_from_dict(self):
        """Test that to_dict and from_dict are inverse operations."""
        # Arrange
        original = IntakeSession(
            session_id="test-roundtrip",
            created_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            first_name="John",
            last_name="Doe",
            phone_number="+15551234567"
        )

        # Act
        roundtrip = IntakeSession.from_dict(original.to_dict())

        # Assert
        assert roundtrip.session_id == original.session_id
        assert roundtrip.first_name == original.first_name
        assert roundtrip.last_name == original.last_name
        assert roundtrip.phone_number == original.phone_number

    # Messages to JSON Tests

    def test_messages_to_json_returns_json_string(self):
        """Test that messages_to_json returns a JSON string."""
        # Arrange - create session with explicit empty messages list
        session = IntakeSession(
            session_id="test-session",
            created_at=datetime.now(timezone.utc),
            messages=[]  # Explicit empty list to avoid shared default
        )

        # Act
        result = session.messages_to_json()

        # Assert
        assert isinstance(result, str)
        assert result == "[]"  # Empty messages list

    def test_messages_to_json_serializes_messages(self):
        """Test that messages_to_json serializes all messages."""
        # Arrange
        session = IntakeSession(
            session_id="test-session",
            created_at=datetime.now(timezone.utc),
            messages=[
                IntakeMessage("user", "Hello", datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc))
            ]
        )

        # Act
        result = session.messages_to_json()

        # Assert
        import json
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["role"] == "user"
        assert parsed[0]["content"] == "Hello"


class TestIntakeSessionManager:
    """Unit tests for IntakeSessionManager class."""

    @patch("intake_agent.api.session.log")
    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.api.session.uuid")
    def test_create_session_generates_session_id(self, mock_uuid, mock_get_cache, mock_log):
        """Test that create_session generates a session ID."""
        # Arrange
        mock_uuid.uuid4.return_value.hex = "abc123def456"
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache

        # Act
        session = IntakeSessionManager.create_session()

        # Assert
        assert session.session_id == "abc123def456"

    @patch("intake_agent.api.session.log")
    @patch("intake_agent.api.session.get_cache")
    def test_create_session_saves_to_cache(self, mock_get_cache, mock_log):
        """Test that create_session saves the session to cache."""
        # Arrange
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache

        # Act
        session = IntakeSessionManager.create_session()

        # Assert
        mock_cache.set.assert_called_once()

    @patch("intake_agent.api.session.log")
    @patch("intake_agent.api.session.get_cache")
    def test_create_session_logs_creation(self, mock_get_cache, mock_log):
        """Test that create_session logs the session creation."""
        # Arrange
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache

        # Act
        session = IntakeSessionManager.create_session()

        # Assert
        mock_log.info.assert_called_once()
        log_message = mock_log.info.call_args[0][0]
        assert session.session_id in log_message

    @patch("intake_agent.api.session.log")
    @patch("intake_agent.api.session.get_cache")
    def test_get_session_retrieves_from_cache(self, mock_get_cache, mock_log):
        """Test that get_session retrieves session from cache."""
        # Arrange
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache
        mock_cache.get.return_value = {
            "session_id": "test-session-789",
            "created_at": "2025-01-15T10:00:00+00:00",
            "patient_creation_pending": False,
            "patient_id": "",
            "patient_mrn": "",
            "first_name": "",
            "last_name": "",
            "date_of_birth": None,
            "phone_number": "",
            "phone_verification_code": "",
            "user_submitted_phone_verified_code": "",
            "health_concerns": "",
            "proposed_appointments": [],
            "preferred_appointment": None,
            "appointment_confirmation_timestamp": None,
            "policy_agreement_timestamp": None,
            "messages": []
        }

        # Act
        session = IntakeSessionManager.get_session("test-session-789")

        # Assert
        mock_cache.get.assert_called_once_with("intake_session:test-session-789")
        assert session.session_id == "test-session-789"

    @patch("intake_agent.api.session.log")
    @patch("intake_agent.api.session.get_cache")
    def test_get_session_logs_retrieval(self, mock_get_cache, mock_log):
        """Test that get_session logs the session retrieval."""
        # Arrange
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache
        mock_cache.get.return_value = {
            "session_id": "test-session-999",
            "created_at": "2025-01-15T10:00:00+00:00",
            "patient_creation_pending": False,
            "patient_id": "",
            "patient_mrn": "",
            "first_name": "",
            "last_name": "",
            "date_of_birth": None,
            "phone_number": "",
            "phone_verification_code": "",
            "user_submitted_phone_verified_code": "",
            "health_concerns": "",
            "proposed_appointments": [],
            "preferred_appointment": None,
            "appointment_confirmation_timestamp": None,
            "policy_agreement_timestamp": None,
            "messages": []
        }

        # Act
        session = IntakeSessionManager.get_session("test-session-999")

        # Assert
        mock_log.info.assert_called_once()
        log_message = mock_log.info.call_args[0][0]
        assert "test-session-999" in log_message
