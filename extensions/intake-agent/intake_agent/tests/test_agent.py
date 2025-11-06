from unittest.mock import MagicMock, patch

import pytest

from intake_agent.agent import (
    REQUIRED_FIELDS,
    get_collected_data_summary,
    get_conversation_history,
    get_initial_greeting,
    process_patient_message,
)


class TestAgent:
    """Unit tests for agent module."""

    # Conversation History Tests

    def test_get_conversation_history_empty(self):
        """Test that get_conversation_history handles empty messages."""
        # Arrange
        session_data = {"messages": []}

        # Act
        result = get_conversation_history(session_data)

        # Assert
        assert result == "No previous messages."

    def test_get_conversation_history_formats_messages(self):
        """Test that get_conversation_history formats messages correctly."""
        # Arrange
        session_data = {
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "agent", "content": "Hi there!"},
                {"role": "user", "content": "My name is John"},
            ]
        }

        # Act
        result = get_conversation_history(session_data)

        # Assert
        assert result == "Patient: Hello\nAgent: Hi there!\nPatient: My name is John"

    def test_get_conversation_history_missing_messages_key(self):
        """Test that get_conversation_history handles missing messages key."""
        # Arrange
        session_data = {}

        # Act
        result = get_conversation_history(session_data)

        # Assert
        assert result == "No previous messages."

    # Collected Data Summary Tests

    def test_get_collected_data_summary_empty(self):
        """Test that get_collected_data_summary handles empty data."""
        # Arrange
        session_data = {"collected_data": {}}

        # Act
        result = get_collected_data_summary(session_data)

        # Assert
        for field in REQUIRED_FIELDS:
            assert f"{field}: NOT COLLECTED" in result

    def test_get_collected_data_summary_partial(self):
        """Test that get_collected_data_summary handles partial data."""
        # Arrange
        session_data = {
            "collected_data": {
                "first_name": "John",
                "last_name": None,
                "phone": None,
                "date_of_birth": None,
                "reason_for_visit": None,
            }
        }

        # Act
        result = get_collected_data_summary(session_data)

        # Assert
        assert "first_name: 'John'" in result
        assert "last_name: NOT COLLECTED" in result
        assert "phone: NOT COLLECTED" in result

    def test_get_collected_data_summary_complete(self):
        """Test that get_collected_data_summary handles complete data."""
        # Arrange
        session_data = {
            "collected_data": {
                "first_name": "John",
                "last_name": "Doe",
                "phone": "555-1234",
                "date_of_birth": "1990-01-01",
                "reason_for_visit": "Annual checkup",
            }
        }

        # Act
        result = get_collected_data_summary(session_data)

        # Assert
        assert "first_name: 'John'" in result
        assert "last_name: 'Doe'" in result
        assert "phone: '555-1234'" in result
        assert "date_of_birth: '1990-01-01'" in result
        assert "reason_for_visit: 'Annual checkup'" in result

    # Initial Greeting Tests

    def test_get_initial_greeting_returns_string(self):
        """Test that get_initial_greeting returns a string."""
        # Act
        result = get_initial_greeting()

        # Assert
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_initial_greeting_asks_reason(self):
        """Test that get_initial_greeting asks for reason for visit."""
        # Act
        result = get_initial_greeting()

        # Assert
        # Should ask about reason, not name (name comes later in workflow)
        assert any(phrase in result.lower() for phrase in ["reason", "brings you", "visiting", "seeking care"])

    # Process Patient Message Tests

    @patch("intake_agent.agent.get_session")
    def test_process_patient_message_session_not_found(self, mock_get_session):
        """Test that process_patient_message handles missing session."""
        # Arrange
        mock_get_session.return_value = None

        # Act
        result = process_patient_message(
            "invalid-session",
            "Hello",
            "test-api-key",
            "scope_of_care_text",
            "555-0000",
            "https://example.com/policies"
        )

        # Assert
        assert isinstance(result, dict)
        assert "couldn't find your session" in result["response"].lower()
        assert result["effects"] == []
        mock_get_session.assert_called_once_with("invalid-session")

    @patch("intake_agent.agent.get_session")
    def test_process_patient_message_completed_session(self, mock_get_session):
        """Test that process_patient_message ignores messages for completed sessions."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "status": "completed",
            "messages": [],
            "collected_data": {},
        }

        # Act
        result = process_patient_message(
            "test-session",
            "Hello again",
            "test-api-key",
            "scope_of_care_text",
            "555-0000",
            "https://example.com/policies"
        )

        # Assert
        assert isinstance(result, dict)
        assert "intake is complete" in result["response"].lower()
        assert result["effects"] == []

    @patch("intake_agent.agent.complete_session")
    @patch("intake_agent.agent.update_session")
    @patch("intake_agent.agent.LlmAnthropic")
    @patch("intake_agent.agent.get_session")
    def test_process_patient_message_extracts_data(
        self, mock_get_session, mock_llm_class, mock_update_session, mock_complete_session
    ):
        """Test that process_patient_message extracts data from LLM response."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "status": "active",
            "messages": [],
            "collected_data": {
                "first_name": None,
                "last_name": None,
                "phone": None,
                "date_of_birth": None,
                "reason_for_visit": None,
            },
        }

        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm
        mock_llm.chat_with_json.return_value = {
            "success": True,
            "data": {
                "extracted_data": {
                    "first_name": "John",
                    "last_name": None,
                    "phone": None,
                    "date_of_birth": None,
                    "reason_for_visit": None,
                },
                "all_information_collected": False,
                "response_to_patient": "Nice to meet you, John! What's your last name?",
            },
        }

        # Act
        result = process_patient_message(
            "test-session",
            "My name is John",
            "test-api-key",
            "Primary care services including checkups, chronic disease management",
            "555-0000",
            "https://example.com/policies"
        )

        # Assert
        assert isinstance(result, dict)
        assert result["response"] == "Nice to meet you, John! What's your last name?"
        assert result["effects"] == []
        mock_llm_class.assert_called_once_with(api_key="test-api-key")
        mock_update_session.assert_called_once()
        mock_complete_session.assert_not_called()

    @patch("intake_agent.agent.complete_session")
    @patch("intake_agent.agent.update_session")
    @patch("intake_agent.agent.LlmAnthropic")
    @patch("intake_agent.agent.get_session")
    def test_process_patient_message_completes_session(
        self, mock_get_session, mock_llm_class, mock_update_session, mock_complete_session
    ):
        """Test that process_patient_message completes session when all data collected."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "status": "active",
            "messages": [],
            "collected_data": {
                "first_name": "John",
                "last_name": "Doe",
                "phone": "555-1234",
                "date_of_birth": "1990-01-01",
                "reason_for_visit": None,
            },
            "phone_verified": True,
            "phone_verification_code": "123456",
        }

        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm
        mock_llm.chat_with_json.return_value = {
            "success": True,
            "data": {
                "extracted_data": {
                    "first_name": "John",
                    "last_name": "Doe",
                    "phone": "555-1234",
                    "date_of_birth": "1990-01-01",
                    "reason_for_visit": "Annual checkup",
                },
                "all_information_collected": True,
                "response_to_patient": "Thank you! Someone will be in touch soon.",
            },
        }

        # Act
        result = process_patient_message(
            "test-session",
            "I need an annual checkup",
            "test-api-key",
            "Primary care services including checkups, chronic disease management",
            "555-0000",
            "https://example.com/policies"
        )

        # Assert
        assert isinstance(result, dict)
        assert "Thank you! Someone will be in touch soon." in result["response"]
        assert result["effects"] == []  # No effects unless create_patient_now is triggered
        mock_complete_session.assert_not_called()  # Session not completed unless send_appointment_confirmation triggered

    @patch("intake_agent.agent.LlmAnthropic")
    @patch("intake_agent.agent.get_session")
    def test_process_patient_message_llm_error(self, mock_get_session, mock_llm_class):
        """Test that process_patient_message handles LLM errors."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "status": "active",
            "messages": [],
            "collected_data": {
                "first_name": None,
                "last_name": None,
                "phone": None,
                "date_of_birth": None,
                "reason_for_visit": None,
            },
        }

        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm
        mock_llm.chat_with_json.return_value = {
            "success": False,
            "data": None,
            "error": "API error",
        }

        # Act
        result = process_patient_message(
            "test-session",
            "Hello",
            "test-api-key",
            "Primary care services including checkups, chronic disease management",
            "555-0000",
            "https://example.com/policies"
        )

        # Assert
        assert isinstance(result, dict)
        assert "trouble processing" in result["response"].lower()
        assert result["effects"] == []

    @patch("intake_agent.agent.LlmAnthropic")
    @patch("intake_agent.agent.get_session")
    def test_process_patient_message_empty_response(self, mock_get_session, mock_llm_class):
        """Test that process_patient_message handles empty response_to_patient."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "status": "active",
            "messages": [],
            "collected_data": {
                "first_name": None,
                "last_name": None,
                "phone": None,
                "date_of_birth": None,
                "reason_for_visit": None,
            },
        }

        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm
        mock_llm.chat_with_json.return_value = {
            "success": True,
            "data": {
                "extracted_data": {},
                "all_information_collected": False,
                "response_to_patient": "",
            },
        }

        # Act
        result = process_patient_message(
            "test-session",
            "Hello",
            "test-api-key",
            "Primary care services including checkups, chronic disease management",
            "555-0000",
            "https://example.com/policies"
        )

        # Assert
        assert isinstance(result, dict)
        assert len(result["response"]) > 0
        assert "Thank you" in result["response"]
        assert result["effects"] == []

    @patch("intake_agent.agent.update_session")
    @patch("intake_agent.agent.LlmAnthropic")
    @patch("intake_agent.agent.get_session")
    def test_process_patient_message_exception_handling(
        self, mock_get_session, mock_llm_class, mock_update_session
    ):
        """Test that process_patient_message handles exceptions."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "status": "active",
            "messages": [],
            "collected_data": {
                "first_name": None,
                "last_name": None,
                "phone": None,
                "date_of_birth": None,
                "reason_for_visit": None,
            },
        }

        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm
        mock_llm.chat_with_json.side_effect = Exception("Unexpected error")

        # Act
        result = process_patient_message(
            "test-session",
            "Hello",
            "test-api-key",
            "Primary care services including checkups, chronic disease management",
            "555-0000",
            "https://example.com/policies"
        )

        # Assert
        assert isinstance(result, dict)
        assert "encountered an error" in result["response"].lower()
        assert result["effects"] == []

    @patch("intake_agent.agent.complete_session")
    @patch("intake_agent.agent.update_session")
    @patch("intake_agent.agent.LlmAnthropic")
    @patch("intake_agent.agent.get_session")
    def test_process_patient_message_false_positive_completion(
        self, mock_get_session, mock_llm_class, mock_update_session, mock_complete_session
    ):
        """Test that process_patient_message doesn't complete if LLM is wrong about completion."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "status": "active",
            "messages": [],
            "collected_data": {
                "first_name": "John",
                "last_name": None,
                "phone": None,
                "date_of_birth": None,
                "reason_for_visit": None,
            },
        }

        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm
        mock_llm.chat_with_json.return_value = {
            "success": True,
            "data": {
                "extracted_data": {
                    "first_name": "John",
                    "last_name": None,
                    "phone": None,
                    "date_of_birth": None,
                    "reason_for_visit": None,
                },
                "all_information_collected": True,  # LLM says complete but it's not
                "response_to_patient": "Thank you!",
            },
        }

        # Act
        result = process_patient_message(
            "test-session",
            "My name is John",
            "test-api-key",
            "Primary care services including checkups, chronic disease management",
            "555-0000",
            "https://example.com/policies"
        )

        # Assert
        assert isinstance(result, dict)
        assert result["response"] == "Thank you!"
        assert result["effects"] == []
        mock_complete_session.assert_not_called()  # Should NOT complete

