from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from intake_agent.agent import IntakeAgent
from intake_agent.api.session import IntakeSession, ProposedAppointment


class TestIntakeAgent:
    """Unit tests for IntakeAgent class."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock IntakeSession for testing."""
        return IntakeSession(
            session_id="test-session-123",
            created_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            first_name="John",
            last_name="Doe",
            phone_number="+15551234567",
        )

    @pytest.fixture
    def agent(self, mock_session):
        """Create an IntakeAgent instance for testing."""
        return IntakeAgent(
            session=mock_session,
            llm_api_key="test-api-key",
            scope_of_care="Primary Care",
            fallback_phone_number="555-0000",
            policies_url="https://example.com/policies",
            twilio_account_sid="AC123",
            twilio_auth_token="test-token",
            twilio_phone_number="+15559876543",
        )

    # Initialization Tests

    @patch("intake_agent.agent.LlmAnthropic")
    def test_init_creates_llm_instance(self, mock_llm_class, mock_session):
        """Test that __init__ creates an LLM instance."""
        # Act
        agent = IntakeAgent(
            session=mock_session,
            llm_api_key="test-key",
            scope_of_care="Primary Care",
            fallback_phone_number="555-0000",
            policies_url="https://example.com/policies",
        )

        # Assert
        mock_llm_class.assert_called_once_with(api_key="test-key")
        assert agent.session == mock_session
        assert agent.scope_of_care == "Primary Care"
        assert agent.fallback_phone_number == "555-0000"
        assert agent.policies_url == "https://example.com/policies"

    @patch("intake_agent.agent.LlmAnthropic")
    def test_init_sets_twilio_credentials(self, mock_llm_class, mock_session):
        """Test that __init__ sets Twilio credentials."""
        # Act
        agent = IntakeAgent(
            session=mock_session,
            llm_api_key="test-key",
            scope_of_care="Primary Care",
            fallback_phone_number="555-0000",
            policies_url="https://example.com/policies",
            twilio_account_sid="AC123",
            twilio_auth_token="token",
            twilio_phone_number="+15551234567",
        )

        # Assert
        assert agent.twilio_account_sid == "AC123"
        assert agent.twilio_auth_token == "token"
        assert agent.twilio_phone_number == "+15551234567"

    # Greeting Tests

    @patch("intake_agent.agent.AGENT_PERSONALITY", "warm_professional")
    @patch("intake_agent.agent.AGENT_NAME", "Sarah")
    def test_greeting_warm_professional(self):
        """Test that greeting returns warm_professional greeting."""
        # Act
        result = IntakeAgent.greeting()

        # Assert
        assert "Hello!" in result
        assert "Sarah" in result
        assert "what brings you in today?" in result

    @patch("intake_agent.agent.AGENT_PERSONALITY", "efficient_direct")
    @patch("intake_agent.agent.AGENT_NAME", "Alex")
    def test_greeting_efficient_direct(self):
        """Test that greeting returns efficient_direct greeting."""
        # Act
        result = IntakeAgent.greeting()

        # Assert
        assert "Hello." in result
        assert "Alex" in result
        assert "what's the reason for your visit?" in result

    @patch("intake_agent.agent.AGENT_PERSONALITY", "empathetic_supportive")
    @patch("intake_agent.agent.AGENT_NAME", "Jordan")
    def test_greeting_empathetic_supportive(self):
        """Test that greeting returns empathetic_supportive greeting."""
        # Act
        result = IntakeAgent.greeting()

        # Assert
        assert "Hello and welcome!" in result
        assert "Jordan" in result
        assert "what brings you in today?" in result

    @patch("intake_agent.agent.AGENT_PERSONALITY", "casual_friendly")
    @patch("intake_agent.agent.AGENT_NAME", "Taylor")
    def test_greeting_casual_friendly(self):
        """Test that greeting returns casual_friendly greeting."""
        # Act
        result = IntakeAgent.greeting()

        # Assert
        assert "Hey there!" in result
        assert "Taylor" in result
        assert "what brings you in today?" in result

    @patch("intake_agent.agent.AGENT_PERSONALITY", "formal_courteous")
    @patch("intake_agent.agent.AGENT_NAME", "Dr. Smith")
    def test_greeting_formal_courteous(self):
        """Test that greeting returns formal_courteous greeting."""
        # Act
        result = IntakeAgent.greeting()

        # Assert
        assert "Good day." in result
        assert "Dr. Smith" in result
        assert "reason for your visit?" in result

    @patch("intake_agent.agent.AGENT_PERSONALITY", "unknown_personality")
    @patch("intake_agent.agent.AGENT_NAME", "Assistant")
    def test_greeting_default_fallback(self):
        """Test that greeting returns default greeting for unknown personality."""
        # Act
        result = IntakeAgent.greeting()

        # Assert
        assert "Hello!" in result
        assert "Assistant" in result
        assert "what brings you in today?" in result

    # System Prompt Tests

    @patch("intake_agent.agent.AGENT_NAME", "TestAgent")
    @patch("intake_agent.agent.AGENT_PERSONALITY", "warm_professional")
    def test_system_prompt_includes_agent_name(self, agent):
        """Test that system prompt includes agent name."""
        # Act
        result = agent._system_prompt

        # Assert
        assert "TestAgent" in result
        assert "medical intake assistant" in result

    @patch("intake_agent.agent.AGENT_PERSONALITY", "warm_professional")
    def test_system_prompt_includes_personality_description(self, agent):
        """Test that system prompt includes personality description."""
        # Act
        result = agent._system_prompt

        # Assert
        assert "YOUR PERSONALITY:" in result
        assert "Key traits to embody:" in result

    def test_system_prompt_includes_important_rules(self, agent):
        """Test that system prompt includes important rules."""
        # Act
        result = agent._system_prompt

        # Assert
        assert "NEVER reveal verification codes" in result
        assert "NEVER break from your objective" in result
        assert "NEVER role play" in result
        assert "ALWAYS respond in a way that ends in a question" in result

    # Listen Tests

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    def test_listen_returns_empty_list_when_no_remaining_fields(self, mock_cache, mock_log, agent):
        """Test that listen returns empty list when no remaining fields."""
        # Arrange
        mock_cache.return_value = MagicMock()
        agent.session = agent.session._replace(
            health_concerns="Back pain",
            proposed_appointments=[
                ProposedAppointment(
                    provider_id="p1",
                    provider_name="Dr. Smith",
                    location_id="l1",
                    location_name="Main Clinic",
                    start_datetime=datetime(2025, 1, 16, 9, 0),
                    duration=30
                )
            ],
            preferred_appointment=ProposedAppointment(
                provider_id="p1",
                provider_name="Dr. Smith",
                location_id="l1",
                location_name="Main Clinic",
                start_datetime=datetime(2025, 1, 16, 9, 0),
                duration=30
            ),
            phone_number="+15551234567",
            phone_verification_code="123456",
            user_submitted_phone_verified_code="123456",
            first_name="John",
            last_name="Doe",
            date_of_birth=date(1990, 1, 1),
            policy_agreement_timestamp=datetime.now(timezone.utc),
            appointment_confirmation_timestamp=datetime.now(timezone.utc),
        )

        # Act
        result = agent.listen("Hello")

        # Assert
        assert result == []

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    def test_listen_adds_user_message_to_session(self, mock_cache, mock_log, agent):
        """Test that listen adds user message to session."""
        # Arrange
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance
        agent.llm.chat_with_json = MagicMock(return_value={
            "success": True,
            "data": [{"field_name": "health_concerns", "field_value": "Back pain"}]
        })

        # Act
        agent.listen("I have back pain")

        # Assert
        assert len(agent.session.messages) > 0
        assert agent.session.messages[-1].role == "user"
        assert agent.session.messages[-1].content == "I have back pain"

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    def test_listen_calls_llm_with_correct_prompts(self, mock_cache, mock_log, agent):
        """Test that listen calls LLM with correct prompts."""
        # Arrange
        mock_cache.return_value = MagicMock()
        agent.llm.chat_with_json = MagicMock(return_value={
            "success": True,
            "data": [{"field_name": "health_concerns", "field_value": "Back pain"}]
        })

        # Act
        agent.listen("I have back pain")

        # Assert
        agent.llm.chat_with_json.assert_called_once()
        call_args = agent.llm.chat_with_json.call_args
        assert "system_prompt" in call_args.kwargs
        assert "user_prompt" in call_args.kwargs
        assert "I have back pain" in call_args.kwargs["user_prompt"]
        assert "health_concerns" in call_args.kwargs["user_prompt"]

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    def test_listen_returns_empty_list_on_llm_error(self, mock_cache, mock_log, agent):
        """Test that listen returns empty list on LLM error."""
        # Arrange
        mock_cache.return_value = MagicMock()
        agent.llm.chat_with_json = MagicMock(return_value={
            "success": False,
            "error": "API timeout"
        })

        # Act
        result = agent.listen("I have back pain")

        # Assert
        assert result == []
        mock_log.info.assert_called()

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    def test_listen_updates_session_with_extracted_field(self, mock_cache, mock_log, agent):
        """Test that listen updates session with extracted field."""
        # Arrange
        mock_cache.return_value = MagicMock()
        agent.llm.chat_with_json = MagicMock(return_value={
            "success": True,
            "data": [{"field_name": "health_concerns", "field_value": "Back pain"}]
        })

        # Act
        agent.listen("I have back pain")

        # Assert
        assert agent.session.health_concerns == "Back pain"

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    def test_listen_ignores_internal_fields(self, mock_cache, mock_log, agent):
        """Test that listen ignores extraction of internal fields."""
        # Arrange
        mock_cache.return_value = MagicMock()
        agent.llm.chat_with_json = MagicMock(return_value={
            "success": True,
            "data": [
                {"field_name": "health_concerns", "field_value": "Back pain"},
                {"field_name": "session_id", "field_value": "hacked"},
            ]
        })
        original_session_id = agent.session.session_id

        # Act
        agent.listen("I have back pain")

        # Assert
        assert agent.session.health_concerns == "Back pain"
        assert agent.session.session_id == original_session_id
        mock_log.warning.assert_called()

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.agent.Toolkit.create_patient")
    def test_listen_creates_patient_when_sufficient_data(self, mock_create_patient, mock_cache, mock_log, agent):
        """Test that listen creates patient when sufficient data is available."""
        # Arrange
        mock_cache.return_value = MagicMock()
        mock_effect = MagicMock()
        mock_create_patient.return_value = mock_effect

        agent.session = agent.session._replace(
            first_name="John",
            last_name="Doe",
            date_of_birth=date(1990, 1, 1),
            phone_number="+15551234567",
            phone_verification_code="123456",
            user_submitted_phone_verified_code="123456",
        )
        agent.llm.chat_with_json = MagicMock(return_value={
            "success": True,
            "data": [{"field_name": "health_concerns", "field_value": "Back pain"}]
        })

        # Act
        result = agent.listen("I have back pain")

        # Assert
        mock_create_patient.assert_called_once()
        assert mock_effect in result
        assert agent.session.patient_creation_pending is True

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.agent.PatientMetadata")
    @patch("intake_agent.agent.Patient")
    def test_listen_polls_for_patient_creation(self, mock_patient_class, mock_metadata_class, mock_cache, mock_log, agent):
        """Test that listen polls for patient creation when pending."""
        # Arrange
        mock_cache.return_value = MagicMock()
        agent.session = agent.session._replace(patient_creation_pending=True)

        # Mock metadata lookup
        mock_metadata = MagicMock()
        mock_patient = MagicMock()
        mock_patient.id = "patient-123"
        mock_patient.mrn = "MRN-456"
        mock_metadata.patient = mock_patient
        mock_metadata_class.objects.filter.return_value.first.return_value = mock_metadata
        mock_patient_class.objects.get.return_value = mock_patient

        agent.llm.chat_with_json = MagicMock(return_value={
            "success": True,
            "data": [{"field_name": "health_concerns", "field_value": "Back pain"}]
        })

        # Act
        agent.listen("I have back pain")

        # Assert
        assert agent.session.patient_id == "patient-123"
        assert agent.session.patient_mrn == "MRN-456"
        assert agent.session.patient_creation_pending is False

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    def test_listen_calls_postread_method_when_exists(self, mock_cache, mock_log, agent):
        """Test that listen calls postread method when it exists."""
        # Arrange
        mock_cache.return_value = MagicMock()
        agent.llm.chat_with_json = MagicMock(return_value={
            "success": True,
            "data": [{"field_name": "date_of_birth", "field_value": "1990-01-01"}]
        })

        # Act
        agent.listen("I was born on January 1, 1990")

        # Assert
        assert agent.session.date_of_birth == date(1990, 1, 1)

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    def test_listen_saves_session(self, mock_cache, mock_log, agent):
        """Test that listen saves session."""
        # Arrange
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance
        agent.llm.chat_with_json = MagicMock(return_value={
            "success": True,
            "data": [{"field_name": "health_concerns", "field_value": "Back pain"}]
        })

        # Act
        agent.listen("I have back pain")

        # Assert
        mock_cache_instance.set.assert_called()

    # Respond Tests

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    def test_respond_returns_completion_message_when_no_remaining_fields(self, mock_cache, mock_log, agent):
        """Test that respond returns completion message when no remaining fields."""
        # Arrange
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        # Set up all target fields to simulate completion
        agent.session = agent.session._replace(
            health_concerns="Back pain",
            proposed_appointments=[
                ProposedAppointment(
                    provider_id="p1",
                    provider_name="Dr. Smith",
                    location_id="l1",
                    location_name="Main Clinic",
                    start_datetime=datetime(2025, 1, 16, 9, 0),
                    duration=30
                )
            ],
            preferred_appointment=ProposedAppointment(
                provider_id="p1",
                provider_name="Dr. Smith",
                location_id="l1",
                location_name="Main Clinic",
                start_datetime=datetime(2025, 1, 16, 9, 0),
                duration=30
            ),
            phone_number="+15551234567",
            phone_verification_code="123456",
            user_submitted_phone_verified_code="123456",
            first_name="John",
            last_name="Doe",
            date_of_birth=date(1990, 1, 1),
            policy_agreement_timestamp=datetime.now(timezone.utc),
            appointment_confirmation_timestamp=datetime.now(timezone.utc),
        )

        # Act
        result = agent.respond()

        # Assert
        assert "concluded" in result

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    def test_respond_calls_llm_with_correct_prompts(self, mock_cache, mock_log, agent):
        """Test that respond calls LLM with correct prompts."""
        # Arrange
        mock_cache.return_value = MagicMock()
        agent.llm.chat_with_json = MagicMock(return_value={
            "success": True,
            "data": {"agent_response_to_user": "What are your health concerns today?"}
        })

        # Act
        agent.respond()

        # Assert
        agent.llm.chat_with_json.assert_called_once()
        call_args = agent.llm.chat_with_json.call_args
        assert "system_prompt" in call_args.kwargs
        assert "user_prompt" in call_args.kwargs
        assert "health_concerns" in call_args.kwargs["user_prompt"]

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    def test_respond_returns_error_message_on_llm_failure(self, mock_cache, mock_log, agent):
        """Test that respond returns error message on LLM failure."""
        # Arrange
        mock_cache.return_value = MagicMock()
        agent.llm.chat_with_json = MagicMock(return_value={
            "success": False,
            "error": "API timeout"
        })

        # Act
        result = agent.respond()

        # Assert
        assert "error has occurred" in result

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    def test_respond_adds_agent_message_to_session(self, mock_cache, mock_log, agent):
        """Test that respond adds agent message to session."""
        # Arrange
        mock_cache.return_value = MagicMock()
        agent.llm.chat_with_json = MagicMock(return_value={
            "success": True,
            "data": {"agent_response_to_user": "What are your health concerns?"}
        })

        # Act
        result = agent.respond()

        # Assert
        assert len(agent.session.messages) > 0
        assert agent.session.messages[-1].role == "agent"
        assert result == "What are your health concerns?"

    @patch("intake_agent.agent.log")
    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.agent.Toolkit.get_next_available_appointments")
    def test_respond_calls_prewrite_method_when_exists(self, mock_get_appointments, mock_cache, mock_log, agent):
        """Test that respond calls prewrite method when it exists."""
        # Arrange
        mock_cache.return_value = MagicMock()
        mock_appointments = [
            ProposedAppointment(
                provider_id="p1",
                provider_name="Dr. Smith",
                location_id="l1",
                location_name="Main Clinic",
                start_datetime=datetime(2025, 1, 16, 9, 0),
                duration=30
            )
        ]
        mock_get_appointments.return_value = mock_appointments

        agent.session = agent.session._replace(health_concerns="Back pain")
        agent.llm.chat_with_json = MagicMock(return_value={
            "success": True,
            "data": {"agent_response_to_user": "Here are available appointments"}
        })

        # Act
        agent.respond()

        # Assert
        mock_get_appointments.assert_called_once()
        assert agent.session.proposed_appointments == mock_appointments

    # Prewrite/Postread Method Tests

    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.agent.Toolkit.get_next_available_appointments")
    def test_prewrite_proposed_appointments_returns_formatted_appointments(self, mock_get_appointments, mock_cache, agent):
        """Test that prewrite_proposed_appointments returns formatted appointments."""
        # Arrange
        mock_cache.return_value = MagicMock()
        mock_appointments = [
            ProposedAppointment(
                provider_id="p1",
                provider_name="Dr. Smith",
                location_id="l1",
                location_name="Main Clinic",
                start_datetime=datetime(2025, 1, 16, 9, 0),
                duration=30
            ),
            ProposedAppointment(
                provider_id="p2",
                provider_name="Dr. Jones",
                location_id="l2",
                location_name="Virtual",
                start_datetime=datetime(2025, 1, 16, 14, 0),
                duration=20
            )
        ]
        mock_get_appointments.return_value = mock_appointments

        # Act
        result = agent.prewrite_proposed_appointments()

        # Assert
        assert "Dr. Smith" in result
        assert "Dr. Jones" in result
        assert "Main Clinic" in result
        assert agent.session.proposed_appointments == mock_appointments

    def test_postread_preferred_appointment_selects_second_appointment(self, agent):
        """Test that postread_preferred_appointment selects second appointment."""
        # Arrange
        agent.session = agent.session._replace(
            proposed_appointments=[
                ProposedAppointment(
                    provider_id="p1",
                    provider_name="Dr. Smith",
                    location_id="l1",
                    location_name="Main Clinic",
                    start_datetime=datetime(2025, 1, 16, 9, 0),
                    duration=30
                ),
                ProposedAppointment(
                    provider_id="p2",
                    provider_name="Dr. Jones",
                    location_id="l2",
                    location_name="Virtual",
                    start_datetime=datetime(2025, 1, 16, 14, 0),
                    duration=20
                )
            ]
        )

        # Act
        result = agent.postread_preferred_appointment("second appointment")

        # Assert
        assert result["value"].provider_name == "Dr. Jones"
        assert result["effects"] == []

    def test_postread_date_of_birth_converts_string_to_date(self, agent):
        """Test that postread_date_of_birth converts string to date."""
        # Act
        result = agent.postread_date_of_birth("1990-01-01")

        # Assert
        assert result["value"] == date(1990, 1, 1)
        assert result["effects"] == []

    def test_postread_date_of_birth_handles_none(self, agent):
        """Test that postread_date_of_birth handles None."""
        # Act
        result = agent.postread_date_of_birth(None)

        # Assert
        assert result["value"] is None
        assert result["effects"] == []

    @patch("intake_agent.agent.Toolkit.generate_verification_code")
    @patch("intake_agent.agent.Toolkit.send_verification_code")
    @patch("intake_agent.api.session.get_cache")
    def test_prewrite_user_submitted_phone_verified_code_sends_code(
        self, mock_cache, mock_send_code, mock_generate_code, agent
    ):
        """Test that prewrite_user_submitted_phone_verified_code sends verification code."""
        # Arrange
        mock_cache.return_value = MagicMock()
        mock_generate_code.return_value = "123456"
        mock_send_code.return_value = {"success": True}

        # Act
        result = agent.prewrite_user_submitted_phone_verified_code()

        # Assert
        mock_generate_code.assert_called_once()
        mock_send_code.assert_called_once()
        assert "successfully" in result
        assert agent.session.phone_verification_code == "123456"

    @patch("intake_agent.agent.Toolkit.generate_verification_code")
    @patch("intake_agent.agent.Toolkit.send_verification_code")
    @patch("intake_agent.api.session.get_cache")
    def test_prewrite_user_submitted_phone_verified_code_handles_send_failure(
        self, mock_cache, mock_send_code, mock_generate_code, agent
    ):
        """Test that prewrite_user_submitted_phone_verified_code handles send failure."""
        # Arrange
        mock_cache.return_value = MagicMock()
        mock_generate_code.return_value = "123456"
        mock_send_code.return_value = {"success": False}

        # Act
        result = agent.prewrite_user_submitted_phone_verified_code()

        # Assert
        assert "FAILED" in result

    @patch("intake_agent.agent.log")
    def test_prewrite_user_submitted_phone_verified_code_detects_mismatch(self, mock_log, agent):
        """Test that prewrite_user_submitted_phone_verified_code detects code mismatch."""
        # Arrange
        agent.session = agent.session._replace(
            phone_verification_code="123456",
            user_submitted_phone_verified_code="654321",
        )

        # Act
        result = agent.prewrite_user_submitted_phone_verified_code()

        # Assert
        assert "UNSUCCESSFUL" in result

    @patch("intake_agent.agent.log")
    def test_postread_user_submitted_phone_verified_code_validates_matching_code(self, mock_log, agent):
        """Test that postread_user_submitted_phone_verified_code validates matching code."""
        # Arrange
        agent.session = agent.session._replace(phone_verification_code="123456")

        # Act
        result = agent.postread_user_submitted_phone_verified_code("123456")

        # Assert
        assert result["value"] == "123456"
        assert result["effects"] == []

    @patch("intake_agent.agent.log")
    def test_postread_user_submitted_phone_verified_code_rejects_mismatching_code(self, mock_log, agent):
        """Test that postread_user_submitted_phone_verified_code rejects mismatching code."""
        # Arrange
        agent.session = agent.session._replace(phone_verification_code="123456")

        # Act
        result = agent.postread_user_submitted_phone_verified_code("654321")

        # Assert
        assert result["value"] == ""
        assert result["effects"] == []

    def test_prewrite_policy_agreement_timestamp_returns_policy_link(self, agent):
        """Test that prewrite_policy_agreement_timestamp returns policy link."""
        # Act
        result = agent.prewrite_policy_agreement_timestamp()

        # Assert
        assert "https://example.com/policies" in result
        assert "indicate agreement" in result

    def test_postread_policy_agreement_timestamp_converts_to_datetime(self, agent):
        """Test that postread_policy_agreement_timestamp converts to datetime."""
        # Act
        result = agent.postread_policy_agreement_timestamp("2025-01-15T10:00:00+00:00")

        # Assert
        assert isinstance(result["value"], datetime)
        assert result["effects"] == []

    def test_postread_policy_agreement_timestamp_handles_none(self, agent):
        """Test that postread_policy_agreement_timestamp handles None."""
        # Act
        result = agent.postread_policy_agreement_timestamp(None)

        # Assert
        assert result["value"] is None
        assert result["effects"] == []

    def test_postread_appointment_confirmation_timestamp_converts_to_datetime(self, agent):
        """Test that postread_appointment_confirmation_timestamp converts to datetime."""
        # Act
        result = agent.postread_appointment_confirmation_timestamp("2025-01-15T10:00:00+00:00")

        # Assert
        assert isinstance(result["value"], datetime)
        assert result["effects"] == []

    def test_postread_appointment_confirmation_timestamp_handles_none(self, agent):
        """Test that postread_appointment_confirmation_timestamp handles None."""
        # Act
        result = agent.postread_appointment_confirmation_timestamp(None)

        # Assert
        assert result["value"] is None
        assert result["effects"] == []

    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.agent.Toolkit.send_appointment_confirmation_sms")
    def test_prewrite_appointment_confirmation_timestamp_sends_sms(self, mock_send_sms, mock_cache, agent):
        """Test that prewrite_appointment_confirmation_timestamp sends SMS."""
        # Arrange
        mock_cache.return_value = MagicMock()
        mock_send_sms.return_value = {"success": True}
        agent.session = agent.session._replace(
            phone_number="+15551234567",
            patient_mrn="MRN123",
            preferred_appointment=ProposedAppointment(
                provider_id="p1",
                provider_name="Dr. Smith",
                location_id="l1",
                location_name="Main Clinic",
                start_datetime=datetime(2025, 1, 16, 9, 0),
                duration=30
            )
        )

        # Act
        result = agent.prewrite_appointment_confirmation_timestamp()

        # Assert
        mock_send_sms.assert_called_once()
        assert "already been sent" in result
        assert agent.session.appointment_confirmation_timestamp is not None

    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.agent.Toolkit.send_appointment_confirmation_sms")
    def test_prewrite_appointment_confirmation_timestamp_handles_sms_failure(self, mock_send_sms, mock_cache, agent):
        """Test that prewrite_appointment_confirmation_timestamp handles SMS failure."""
        # Arrange
        mock_cache.return_value = MagicMock()
        mock_send_sms.return_value = {"success": False}
        agent.session = agent.session._replace(
            phone_number="+15551234567",
            patient_mrn="MRN123",
            preferred_appointment=ProposedAppointment(
                provider_id="p1",
                provider_name="Dr. Smith",
                location_id="l1",
                location_name="Main Clinic",
                start_datetime=datetime(2025, 1, 16, 9, 0),
                duration=30
            )
        )

        # Act
        result = agent.prewrite_appointment_confirmation_timestamp()

        # Assert
        assert "FAILED" in result
        assert "call the clinic" in result
