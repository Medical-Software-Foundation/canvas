"""Tests for SubmitHealthRiskAssessment API handler."""

import json
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from health_risk_assessment.protocols.submit_assessment import (
    SubmitHealthRiskAssessment,
    _get_general_health_context,
    _get_physical_activities_context,
    _get_adl_context,
    _get_difficulty_level,
)


# Helper to create a handler with mocked secrets
def _create_handler_with_secrets(body: bytes, secrets: dict | None = None) -> SubmitHealthRiskAssessment:
    """Create a handler with mocked event context and secrets."""
    mock_event = MagicMock()
    mock_event.context = {
        "method": "POST",
        "path": "/submit-hra",
        "query_string": "",
        "body": body,
        "headers": {},
    }

    mock_pattern = MagicMock()
    mock_pattern.fullmatch.return_value = True

    with patch.object(
        SubmitHealthRiskAssessment,
        "_ROUTES",
        new={"POST": [(mock_pattern, "post")]},
    ):
        handler = SubmitHealthRiskAssessment(event=mock_event, secrets=secrets or {})

    return handler


class TestSubmitHealthRiskAssessmentConfiguration:
    """Tests for API configuration."""

    def test_base_path_is_correct(self) -> None:
        """Test that API base path is configured correctly."""
        assert SubmitHealthRiskAssessment.BASE_PATH == "/plugin-io/api/health_risk_assessment"

    def test_questionnaire_code_is_correct(self) -> None:
        """Test that questionnaire code matches YAML."""
        assert SubmitHealthRiskAssessment.QUESTIONNAIRE_CODE == "HRA_AWV"
        assert SubmitHealthRiskAssessment.QUESTIONNAIRE_CODE_SYSTEM == "INTERNAL"


class TestSubmitHealthRiskAssessmentAuthentication:
    """Tests for API authentication using StaffSessionAuthMixin."""

    def test_authenticate_returns_true_when_staff_logged_in(self) -> None:
        """Test that authentication returns True when staff user is logged in."""
        from canvas_sdk.handlers.simple_api.security import InvalidCredentialsError

        mock_event = MagicMock()
        mock_event.context = {"method": "POST", "path": "/submit-hra", "query_string": ""}

        # Mock credentials with staff user (StaffSessionAuthMixin checks type == "Staff")
        mock_credentials = MagicMock()
        mock_credentials.logged_in_user = {"id": "staff-123", "type": "Staff"}

        # Mock the _ROUTES with proper regex pattern
        mock_pattern = MagicMock()
        mock_pattern.fullmatch.return_value = True

        with patch.object(
            SubmitHealthRiskAssessment,
            "_ROUTES",
            new={"POST": [(mock_pattern, "post")]},
        ):
            handler = SubmitHealthRiskAssessment(event=mock_event)
            result = handler.authenticate(mock_credentials)
            assert result is True

    def test_authenticate_returns_false_when_not_logged_in(self) -> None:
        """Test that authentication raises error when user is not staff."""
        from canvas_sdk.handlers.simple_api.security import InvalidCredentialsError

        mock_event = MagicMock()
        mock_event.context = {"method": "POST", "path": "/submit-hra", "query_string": ""}

        # Mock credentials with patient user (not staff)
        mock_credentials = MagicMock()
        mock_credentials.logged_in_user = {"id": "patient-123", "type": "Patient"}

        # Mock the _ROUTES with proper regex pattern
        mock_pattern = MagicMock()
        mock_pattern.fullmatch.return_value = True

        with patch.object(
            SubmitHealthRiskAssessment,
            "_ROUTES",
            new={"POST": [(mock_pattern, "post")]},
        ):
            handler = SubmitHealthRiskAssessment(event=mock_event)
            # StaffSessionAuthMixin raises InvalidCredentialsError for non-staff users
            with pytest.raises(InvalidCredentialsError):
                handler.authenticate(mock_credentials)


class TestSubmitHealthRiskAssessmentPost:
    """Tests for POST endpoint."""

    def _create_handler_with_body(self, body: bytes) -> SubmitHealthRiskAssessment:
        """Create a handler with mocked event context including body."""
        mock_event = MagicMock()
        mock_event.context = {
            "method": "POST",
            "path": "/submit-hra",
            "query_string": "",
            "body": body,
            "headers": {},
        }

        mock_pattern = MagicMock()
        mock_pattern.fullmatch.return_value = True

        with patch.object(
            SubmitHealthRiskAssessment,
            "_ROUTES",
            new={"POST": [(mock_pattern, "post")]},
        ):
            handler = SubmitHealthRiskAssessment(event=mock_event)

        return handler

    def test_submit_hra_returns_error_when_note_not_found(self) -> None:
        """Test that submit_hra returns error when note is not found."""
        body = json.dumps({"note_id": 999, "responses": {}}).encode("utf-8")
        handler = self._create_handler_with_body(body)

        # Mock the request property
        mock_request = MagicMock()
        mock_request.body = body

        with patch.object(type(handler), "request", new=PropertyMock(return_value=mock_request)):
            with patch(
                "health_risk_assessment.protocols.submit_assessment.Note.objects"
            ) as mock_note_objects:
                mock_note_objects.filter.return_value.first.return_value = None

                responses = handler.submit_hra()

        # Should return JSONResponse with error
        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == 404

    def test_submit_hra_returns_error_when_questionnaire_not_found(
        self, valid_form_data: dict
    ) -> None:
        """Test that submit_hra returns error when questionnaire doesn't exist."""
        body = json.dumps(valid_form_data).encode("utf-8")
        handler = _create_handler_with_secrets(body, secrets={"OUTPUT_MODE": "questionnaire"})

        mock_request = MagicMock()
        mock_request.body = body

        # Create mock note
        mock_note = MagicMock()
        mock_note.id = "test-note-uuid"

        with patch.object(type(handler), "request", new=PropertyMock(return_value=mock_request)):
            with patch(
                "health_risk_assessment.protocols.submit_assessment.Note.objects"
            ) as mock_note_objects:
                with patch(
                    "health_risk_assessment.protocols.submit_assessment.Questionnaire.objects"
                ) as mock_q_objects:
                    mock_note_objects.filter.return_value.first.return_value = mock_note
                    mock_q_objects.filter.return_value.first.return_value = None

                    responses = handler.submit_hra()

                    # Verify Questionnaire.objects.filter was called with status="AC"
                    mock_q_objects.filter.assert_called_once_with(
                        code="HRA_AWV", code_system="INTERNAL", status="AC"
                    )

                    # Should return JSONResponse with error
                    assert len(responses) == 1
                    response = responses[0]
                    assert response.status_code == 404

    def test_submit_hra_returns_error_on_invalid_json(self) -> None:
        """Test that submit_hra returns error when body is invalid JSON."""
        body = b"not valid json"
        handler = self._create_handler_with_body(body)

        mock_request = MagicMock()
        mock_request.body = body

        with patch.object(type(handler), "request", new=PropertyMock(return_value=mock_request)):
            responses = handler.submit_hra()

        # Should return JSONResponse with error
        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == 400

    def test_submit_hra_creates_questionnaire_command_on_valid_submission(
        self,
        mock_questionnaire: MagicMock,
        valid_form_data: dict,
    ) -> None:
        """Test that submit_hra creates and commits QuestionnaireCommand on valid data."""
        body = json.dumps(valid_form_data).encode("utf-8")
        handler = _create_handler_with_secrets(body, secrets={"OUTPUT_MODE": "questionnaire"})

        mock_request = MagicMock()
        mock_request.body = body

        # Create mock note
        mock_note = MagicMock()
        mock_note.id = "test-note-uuid"

        with patch.object(type(handler), "request", new=PropertyMock(return_value=mock_request)):
            with patch(
                "health_risk_assessment.protocols.submit_assessment.Note.objects"
            ) as mock_note_objects:
                with patch(
                    "health_risk_assessment.protocols.submit_assessment.Questionnaire.objects"
                ) as mock_q_objects:
                    with patch(
                        "health_risk_assessment.protocols.submit_assessment.QuestionnaireCommand"
                    ) as mock_command_class:
                        mock_note_objects.filter.return_value.first.return_value = mock_note
                        mock_q_objects.filter.return_value.first.return_value = mock_questionnaire
                        mock_command = MagicMock()
                        mock_command_class.return_value = mock_command
                        mock_command.questions = []
                        mock_command.originate.return_value = MagicMock()
                        mock_command.edit.return_value = MagicMock()
                        mock_command.commit.return_value = MagicMock()

                        responses = handler.submit_hra()

                        # Verify Note.objects.filter was called with dbid
                        mock_note_objects.filter.assert_called_once_with(dbid="test-note-123")

                        # Verify Questionnaire.objects.filter was called with status="AC"
                        mock_q_objects.filter.assert_called_once_with(
                            code="HRA_AWV", code_system="INTERNAL", status="AC"
                        )

                        # Verify QuestionnaireCommand was created with note UUID
                        call_kwargs = mock_command_class.call_args[1]
                        assert call_kwargs["note_uuid"] == "test-note-uuid"
                        assert call_kwargs["questionnaire_id"] == str(mock_questionnaire.id)

                        # Verify command methods were called
                        mock_command.originate.assert_called_once()
                        mock_command.edit.assert_called_once()
                        mock_command.commit.assert_called_once()

                        # Should return originate, edit, commit, and JSONResponse
                        assert len(responses) == 4

    def test_submit_hra_sets_responses_on_questions(
        self,
        mock_questionnaire: MagicMock,
    ) -> None:
        """Test that submit_hra correctly sets responses on questionnaire questions."""
        form_data = {
            "note_id": 123,
            "responses": {
                "HRA_GENERAL_HEALTH": "HRA_GENERAL_HEALTH_GOOD",
            },
        }
        body = json.dumps(form_data).encode("utf-8")
        handler = _create_handler_with_secrets(body, secrets={"OUTPUT_MODE": "questionnaire"})

        mock_request = MagicMock()
        mock_request.body = body

        # Create mock note
        mock_note = MagicMock()
        mock_note.id = "test-note-uuid"

        # Create mock question with response options
        mock_question = MagicMock()
        mock_question.coding = {"code": "HRA_GENERAL_HEALTH"}
        mock_response_option = MagicMock()
        mock_response_option.coding = {"code": "HRA_GENERAL_HEALTH_GOOD"}
        mock_question.options = [mock_response_option]

        with patch.object(type(handler), "request", new=PropertyMock(return_value=mock_request)):
            with patch(
                "health_risk_assessment.protocols.submit_assessment.Note.objects"
            ) as mock_note_objects:
                with patch(
                    "health_risk_assessment.protocols.submit_assessment.Questionnaire.objects"
                ) as mock_q_objects:
                    with patch(
                        "health_risk_assessment.protocols.submit_assessment.QuestionnaireCommand"
                    ) as mock_command_class:
                        mock_note_objects.filter.return_value.first.return_value = mock_note
                        mock_q_objects.filter.return_value.first.return_value = mock_questionnaire
                        mock_command = MagicMock()
                        mock_command_class.return_value = mock_command
                        mock_command.questions = [mock_question]
                        mock_command.originate.return_value = MagicMock()
                        mock_command.edit.return_value = MagicMock()
                        mock_command.commit.return_value = MagicMock()

                        responses = handler.submit_hra()

                        # Verify add_response was called on the question with option parameter
                        mock_question.add_response.assert_called_once_with(option=mock_response_option)

                        # Should return originate, edit, commit, and JSONResponse
                        assert len(responses) == 4

    def test_submit_hra_sets_result_summary(
        self,
        mock_questionnaire: MagicMock,
    ) -> None:
        """Test that submit_hra sets a result summary on the command."""
        form_data = {
            "note_id": 123,
            "responses": {
                "HRA_GENERAL_HEALTH": "HRA_GENERAL_HEALTH_EXCELLENT",
            },
        }
        body = json.dumps(form_data).encode("utf-8")
        handler = _create_handler_with_secrets(body, secrets={"OUTPUT_MODE": "questionnaire"})

        mock_request = MagicMock()
        mock_request.body = body

        # Create mock note
        mock_note = MagicMock()
        mock_note.id = "test-note-uuid"

        with patch.object(type(handler), "request", new=PropertyMock(return_value=mock_request)):
            with patch(
                "health_risk_assessment.protocols.submit_assessment.Note.objects"
            ) as mock_note_objects:
                with patch(
                    "health_risk_assessment.protocols.submit_assessment.Questionnaire.objects"
                ) as mock_q_objects:
                    with patch(
                        "health_risk_assessment.protocols.submit_assessment.QuestionnaireCommand"
                    ) as mock_command_class:
                        mock_note_objects.filter.return_value.first.return_value = mock_note
                        mock_q_objects.filter.return_value.first.return_value = mock_questionnaire
                        mock_command = MagicMock()
                        mock_command_class.return_value = mock_command
                        mock_command.questions = []
                        mock_command.originate.return_value = MagicMock()
                        mock_command.edit.return_value = MagicMock()
                        mock_command.commit.return_value = MagicMock()

                        handler.submit_hra()

                        # Verify result was set (contains "Excellent")
                        assert mock_command.result == "General Health: Excellent"

    def test_submit_hra_sets_default_result_when_no_general_health(
        self,
        mock_questionnaire: MagicMock,
    ) -> None:
        """Test that submit_hra sets default result when general health is not provided."""
        form_data = {
            "note_id": 123,
            "responses": {},
        }
        body = json.dumps(form_data).encode("utf-8")
        handler = _create_handler_with_secrets(body, secrets={"OUTPUT_MODE": "questionnaire"})

        mock_request = MagicMock()
        mock_request.body = body

        # Create mock note
        mock_note = MagicMock()
        mock_note.id = "test-note-uuid"

        with patch.object(type(handler), "request", new=PropertyMock(return_value=mock_request)):
            with patch(
                "health_risk_assessment.protocols.submit_assessment.Note.objects"
            ) as mock_note_objects:
                with patch(
                    "health_risk_assessment.protocols.submit_assessment.Questionnaire.objects"
                ) as mock_q_objects:
                    with patch(
                        "health_risk_assessment.protocols.submit_assessment.QuestionnaireCommand"
                    ) as mock_command_class:
                        mock_note_objects.filter.return_value.first.return_value = mock_note
                        mock_q_objects.filter.return_value.first.return_value = mock_questionnaire
                        mock_command = MagicMock()
                        mock_command_class.return_value = mock_command
                        mock_command.questions = []
                        mock_command.originate.return_value = MagicMock()
                        mock_command.edit.return_value = MagicMock()
                        mock_command.commit.return_value = MagicMock()

                        handler.submit_hra()

                        # Verify default result was set
                        assert mock_command.result == "Health Risk Assessment completed"


class TestHelperFunctions:
    """Tests for helper functions used in template context building."""

    def test_get_general_health_context_poor(self) -> None:
        """Test general health context returns correct values for poor health."""
        responses = {"HRA_GENERAL_HEALTH": "HRA_GENERAL_HEALTH_POOR"}
        label, css_class = _get_general_health_context(responses)
        assert label == "Poor"
        assert css_class == "poor"

    def test_get_general_health_context_excellent(self) -> None:
        """Test general health context returns correct values for excellent health."""
        responses = {"HRA_GENERAL_HEALTH": "HRA_GENERAL_HEALTH_EXCELLENT"}
        label, css_class = _get_general_health_context(responses)
        assert label == "Excellent"
        assert css_class == "excellent"

    def test_get_general_health_context_very_good(self) -> None:
        """Test general health context returns correct values for very good health."""
        responses = {"HRA_GENERAL_HEALTH": "HRA_GENERAL_HEALTH_VERY_GOOD"}
        label, css_class = _get_general_health_context(responses)
        assert label == "Very good"
        assert css_class == "very-good"

    def test_get_general_health_context_missing(self) -> None:
        """Test general health context returns default when not specified."""
        responses: dict[str, str] = {}
        label, css_class = _get_general_health_context(responses)
        assert label == "Not Specified"
        assert css_class == "good"

    def test_get_difficulty_level_none(self) -> None:
        """Test difficulty level extraction for 'none' response."""
        label, css_class = _get_difficulty_level("HRA_DIFF_STOOPING_NONE", "HRA_DIFF_STOOPING")
        assert label == "No Difficulty"
        assert css_class == "none"

    def test_get_difficulty_level_unable(self) -> None:
        """Test difficulty level extraction for 'unable' response."""
        label, css_class = _get_difficulty_level("HRA_DIFF_LIFTING_UNABLE", "HRA_DIFF_LIFTING")
        assert label == "Unable to Do"
        assert css_class == "unable"

    def test_get_difficulty_level_empty(self) -> None:
        """Test difficulty level extraction for empty response."""
        label, css_class = _get_difficulty_level("", "HRA_DIFF_STOOPING")
        assert label == "N/A"
        assert css_class == "none"

    def test_get_physical_activities_context(self) -> None:
        """Test physical activities context building."""
        responses = {
            "HRA_DIFF_STOOPING": "HRA_DIFF_STOOPING_NONE",
            "HRA_DIFF_LIFTING": "HRA_DIFF_LIFTING_LITTLE",
            "HRA_DIFF_REACHING": "HRA_DIFF_REACHING_SOME",
            "HRA_DIFF_WRITING": "HRA_DIFF_WRITING_LOT",
            "HRA_DIFF_WALKING_QUARTER": "HRA_DIFF_WALKING_QUARTER_UNABLE",
            "HRA_DIFF_HOUSEWORK": "HRA_DIFF_HOUSEWORK_NONE",
        }
        activities = _get_physical_activities_context(responses)

        assert len(activities) == 6
        assert activities[0]["label"] == "Stooping, crouching, or kneeling"
        assert activities[0]["level"] == "No Difficulty"
        assert activities[0]["level_class"] == "none"
        assert activities[1]["level"] == "A Little Difficulty"
        assert activities[2]["level"] == "Some Difficulty"
        assert activities[3]["level"] == "A Lot of Difficulty"
        assert activities[4]["level"] == "Unable to Do"

    def test_get_adl_context_no_response(self) -> None:
        """Test ADL context for 'No' response."""
        responses = {"HRA_ADL_SHOPPING": "HRA_ADL_SHOPPING_NO"}
        adl_items = _get_adl_context(responses)

        shopping = adl_items[0]
        assert shopping["label"] == "Shopping for personal items"
        assert shopping["status_class"] == "no-difficulty"
        assert shopping["response_text"] == "No"
        assert shopping["help_text"] == ""  # No follow-up for "No"
        assert shopping["show_followup"] is False  # Follow-up not shown for "No"
        assert shopping["followup_type"] is None

    def test_get_adl_context_yes_response_with_help_yes(self) -> None:
        """Test ADL context for 'Yes' response with help follow-up 'Yes'."""
        responses = {
            "HRA_ADL_SHOPPING": "HRA_ADL_SHOPPING_YES",
            "HRA_ADL_SHOPPING_HELP": "HRA_ADL_SHOPPING_HELP_YES",
        }
        adl_items = _get_adl_context(responses)

        shopping = adl_items[0]
        assert shopping["status_class"] == "has-difficulty"
        assert shopping["response_text"] == "Yes"
        assert shopping["help_text"] == "Yes"
        assert shopping["show_followup"] is True  # Follow-up shown for "Yes" with valid answer
        assert shopping["followup_type"] == "help"  # "Do you receive help" question

    def test_get_adl_context_yes_response_with_help_no(self) -> None:
        """Test ADL context for 'Yes' response with help follow-up 'No'."""
        responses = {
            "HRA_ADL_SHOPPING": "HRA_ADL_SHOPPING_YES",
            "HRA_ADL_SHOPPING_HELP": "HRA_ADL_SHOPPING_HELP_NO",
        }
        adl_items = _get_adl_context(responses)

        shopping = adl_items[0]
        assert shopping["status_class"] == "has-difficulty"
        assert shopping["response_text"] == "Yes"
        assert shopping["help_text"] == "No"
        assert shopping["show_followup"] is True  # Follow-up shown for "Yes" with valid answer
        assert shopping["followup_type"] == "help"  # "Do you receive help" question

    def test_get_adl_context_yes_response_with_help_na(self) -> None:
        """Test ADL context for 'Yes' response with help follow-up 'N/A'."""
        responses = {
            "HRA_ADL_SHOPPING": "HRA_ADL_SHOPPING_YES",
            "HRA_ADL_SHOPPING_HELP": "HRA_ADL_SHOPPING_HELP_NA",
        }
        adl_items = _get_adl_context(responses)

        shopping = adl_items[0]
        assert shopping["status_class"] == "has-difficulty"
        assert shopping["response_text"] == "Yes"
        assert shopping["help_text"] == "N/A"
        assert shopping["show_followup"] is False  # N/A answer not shown
        assert shopping["followup_type"] == "help"  # "Do you receive help" question

    def test_get_adl_context_yes_response_no_help_answer(self) -> None:
        """Test ADL context for 'Yes' response without help follow-up answer."""
        responses = {"HRA_ADL_SHOPPING": "HRA_ADL_SHOPPING_YES"}
        adl_items = _get_adl_context(responses)

        shopping = adl_items[0]
        assert shopping["status_class"] == "has-difficulty"
        assert shopping["response_text"] == "Yes"
        assert shopping["help_text"] == "N/A"  # Defaults to N/A when no answer
        assert shopping["show_followup"] is False  # No valid answer to show
        assert shopping["followup_type"] == "help"  # "Do you receive help" question

    def test_get_adl_context_dont_know_with_health_yes(self) -> None:
        """Test ADL context for 'Don't Know' response with health follow-up 'Yes'."""
        responses = {
            "HRA_ADL_BATHING": "HRA_ADL_BATHING_DK",
            "HRA_ADL_BATHING_HEALTH": "HRA_ADL_BATHING_HEALTH_YES",  # Uses _HEALTH code
        }
        adl_items = _get_adl_context(responses)

        bathing = adl_items[4]  # Bathing is the 5th item
        assert bathing["status_class"] == "uncertain"
        assert bathing["response_text"] == "Don't Know"
        assert bathing["help_text"] == "Yes"
        assert bathing["show_followup"] is True  # Follow-up shown with valid answer
        assert bathing["followup_type"] == "health"  # "Due to your health?" question

    def test_get_adl_context_dont_know_no_health_answer(self) -> None:
        """Test ADL context for 'Don't Know' response without health answer."""
        responses = {"HRA_ADL_BATHING": "HRA_ADL_BATHING_DK"}
        adl_items = _get_adl_context(responses)

        bathing = adl_items[4]  # Bathing is the 5th item
        assert bathing["status_class"] == "uncertain"
        assert bathing["response_text"] == "Don't Know"
        assert bathing["help_text"] == "N/A"  # Defaults to N/A when no answer
        assert bathing["show_followup"] is False  # No valid answer to show
        assert bathing["followup_type"] == "health"  # "Due to your health?" question

    def test_get_adl_context_not_answered(self) -> None:
        """Test ADL context for unanswered question."""
        responses: dict[str, str] = {}
        adl_items = _get_adl_context(responses)

        shopping = adl_items[0]
        assert shopping["status_class"] == "no-difficulty"
        assert shopping["response_text"] == "N/A"
        assert shopping["help_text"] == ""  # No follow-up for unanswered
        assert shopping["show_followup"] is False  # Follow-up not shown for unanswered
        assert shopping["followup_type"] is None


class TestOutputModeConfiguration:
    """Tests for OUTPUT_MODE secret configuration."""

    def test_custom_command_schema_key_is_configured(self) -> None:
        """Test that custom command schema key is configured."""
        assert SubmitHealthRiskAssessment.CUSTOM_COMMAND_SCHEMA_KEY == "healthRiskAssessmentSummary"

    def test_output_mode_constants_are_defined(self) -> None:
        """Test that output mode constants are defined."""
        assert SubmitHealthRiskAssessment.OUTPUT_MODE_QUESTIONNAIRE == "questionnaire"
        assert SubmitHealthRiskAssessment.OUTPUT_MODE_CUSTOM == "custom"
        assert SubmitHealthRiskAssessment.OUTPUT_MODE_BOTH == "both"
        assert SubmitHealthRiskAssessment.DEFAULT_OUTPUT_MODE == "custom"


class TestOutputModeSubmission:
    """Tests for submission with different output modes."""

    def test_get_output_mode_returns_default_when_not_set(self) -> None:
        """Test that _get_output_mode returns 'custom' when secret is not set."""
        handler = _create_handler_with_secrets(b"{}", secrets={})
        mode = handler._get_output_mode()
        assert mode == "custom"

    def test_get_output_mode_returns_questionnaire(self) -> None:
        """Test that _get_output_mode returns 'questionnaire' when set."""
        handler = _create_handler_with_secrets(b"{}", secrets={"OUTPUT_MODE": "questionnaire"})
        mode = handler._get_output_mode()
        assert mode == "questionnaire"

    def test_get_output_mode_returns_custom(self) -> None:
        """Test that _get_output_mode returns 'custom' when set."""
        handler = _create_handler_with_secrets(b"{}", secrets={"OUTPUT_MODE": "custom"})
        mode = handler._get_output_mode()
        assert mode == "custom"

    def test_get_output_mode_handles_invalid_value(self) -> None:
        """Test that _get_output_mode returns default for invalid values."""
        handler = _create_handler_with_secrets(b"{}", secrets={"OUTPUT_MODE": "invalid"})
        mode = handler._get_output_mode()
        assert mode == "custom"

    def test_get_output_mode_handles_case_insensitive(self) -> None:
        """Test that _get_output_mode handles case insensitive values."""
        handler = _create_handler_with_secrets(b"{}", secrets={"OUTPUT_MODE": "CUSTOM"})
        mode = handler._get_output_mode()
        assert mode == "custom"

    def test_submit_hra_questionnaire_only_mode(
        self,
        mock_questionnaire: MagicMock,
        valid_form_data: dict,
    ) -> None:
        """Test submit_hra in questionnaire-only mode creates only questionnaire command."""
        body = json.dumps(valid_form_data).encode("utf-8")
        handler = _create_handler_with_secrets(body, secrets={"OUTPUT_MODE": "questionnaire"})

        mock_request = MagicMock()
        mock_request.body = body

        mock_note = MagicMock()
        mock_note.id = "test-note-uuid"

        with patch.object(type(handler), "request", new=PropertyMock(return_value=mock_request)):
            with patch(
                "health_risk_assessment.protocols.submit_assessment.Note.objects"
            ) as mock_note_objects:
                with patch(
                    "health_risk_assessment.protocols.submit_assessment.Questionnaire.objects"
                ) as mock_q_objects:
                    with patch(
                        "health_risk_assessment.protocols.submit_assessment.QuestionnaireCommand"
                    ) as mock_command_class:
                        mock_note_objects.filter.return_value.first.return_value = mock_note
                        mock_q_objects.filter.return_value.first.return_value = mock_questionnaire
                        mock_command = MagicMock()
                        mock_command_class.return_value = mock_command
                        mock_command.questions = []
                        mock_command.originate.return_value = MagicMock()
                        mock_command.edit.return_value = MagicMock()
                        mock_command.commit.return_value = MagicMock()

                        responses = handler.submit_hra()

                        # Should return 3 questionnaire effects + 1 JSONResponse
                        assert len(responses) == 4
                        mock_command.originate.assert_called_once()
                        mock_command.edit.assert_called_once()
                        mock_command.commit.assert_called_once()

    def test_submit_hra_custom_only_mode(
        self,
        valid_form_data: dict,
    ) -> None:
        """Test submit_hra in custom-only mode creates only custom command."""
        body = json.dumps(valid_form_data).encode("utf-8")
        handler = _create_handler_with_secrets(body, secrets={"OUTPUT_MODE": "custom"})

        mock_request = MagicMock()
        mock_request.body = body

        mock_note = MagicMock()
        mock_note.id = "test-note-uuid"

        with patch.object(type(handler), "request", new=PropertyMock(return_value=mock_request)):
            with patch(
                "health_risk_assessment.protocols.submit_assessment.Note.objects"
            ) as mock_note_objects:
                with patch(
                    "health_risk_assessment.protocols.submit_assessment.render_to_string"
                ) as mock_render:
                    with patch(
                        "health_risk_assessment.protocols.submit_assessment.CustomCommand"
                    ) as mock_custom_class:
                        mock_note_objects.filter.return_value.first.return_value = mock_note
                        mock_render.return_value = "<html>test</html>"
                        mock_custom_command = MagicMock()
                        mock_custom_class.return_value = mock_custom_command
                        mock_custom_command.originate.return_value = MagicMock()

                        responses = handler.submit_hra()

                        # Should return 1 custom command effect (originate only) + 1 JSONResponse
                        assert len(responses) == 2
                        mock_custom_class.assert_called_once()
                        mock_custom_command.originate.assert_called_once()

                        # Verify schema_key was set
                        call_kwargs = mock_custom_class.call_args[1]
                        assert call_kwargs["schema_key"] == "healthRiskAssessmentSummary"

    def test_submit_hra_both_mode(
        self,
        mock_questionnaire: MagicMock,
        valid_form_data: dict,
    ) -> None:
        """Test submit_hra in 'both' mode creates both commands."""
        body = json.dumps(valid_form_data).encode("utf-8")
        handler = _create_handler_with_secrets(body, secrets={"OUTPUT_MODE": "both"})

        mock_request = MagicMock()
        mock_request.body = body

        mock_note = MagicMock()
        mock_note.id = "test-note-uuid"

        with patch.object(type(handler), "request", new=PropertyMock(return_value=mock_request)):
            with patch(
                "health_risk_assessment.protocols.submit_assessment.Note.objects"
            ) as mock_note_objects:
                with patch(
                    "health_risk_assessment.protocols.submit_assessment.Questionnaire.objects"
                ) as mock_q_objects:
                    with patch(
                        "health_risk_assessment.protocols.submit_assessment.QuestionnaireCommand"
                    ) as mock_q_command_class:
                        with patch(
                            "health_risk_assessment.protocols.submit_assessment.render_to_string"
                        ) as mock_render:
                            with patch(
                                "health_risk_assessment.protocols.submit_assessment.CustomCommand"
                            ) as mock_custom_class:
                                mock_note_objects.filter.return_value.first.return_value = mock_note
                                mock_q_objects.filter.return_value.first.return_value = mock_questionnaire
                                mock_render.return_value = "<html>test</html>"

                                # Mock questionnaire command
                                mock_q_command = MagicMock()
                                mock_q_command_class.return_value = mock_q_command
                                mock_q_command.questions = []
                                mock_q_command.originate.return_value = MagicMock()
                                mock_q_command.edit.return_value = MagicMock()
                                mock_q_command.commit.return_value = MagicMock()

                                # Mock custom command
                                mock_custom_command = MagicMock()
                                mock_custom_class.return_value = mock_custom_command
                                mock_custom_command.originate.return_value = MagicMock()

                                responses = handler.submit_hra()

                                # Should return 3 questionnaire effects + 1 custom effect + 1 JSONResponse
                                assert len(responses) == 5
                                mock_q_command.originate.assert_called_once()
                                mock_q_command.edit.assert_called_once()
                                mock_q_command.commit.assert_called_once()
                                mock_custom_command.originate.assert_called_once()

    def test_submit_hra_response_includes_output_mode(
        self,
        mock_questionnaire: MagicMock,
        valid_form_data: dict,
    ) -> None:
        """Test that submit_hra response includes the output mode used."""
        body = json.dumps(valid_form_data).encode("utf-8")
        handler = _create_handler_with_secrets(body, secrets={"OUTPUT_MODE": "questionnaire"})

        mock_request = MagicMock()
        mock_request.body = body

        mock_note = MagicMock()
        mock_note.id = "test-note-uuid"

        with patch.object(type(handler), "request", new=PropertyMock(return_value=mock_request)):
            with patch(
                "health_risk_assessment.protocols.submit_assessment.Note.objects"
            ) as mock_note_objects:
                with patch(
                    "health_risk_assessment.protocols.submit_assessment.Questionnaire.objects"
                ) as mock_q_objects:
                    with patch(
                        "health_risk_assessment.protocols.submit_assessment.QuestionnaireCommand"
                    ) as mock_command_class:
                        mock_note_objects.filter.return_value.first.return_value = mock_note
                        mock_q_objects.filter.return_value.first.return_value = mock_questionnaire
                        mock_command = MagicMock()
                        mock_command_class.return_value = mock_command
                        mock_command.questions = []
                        mock_command.originate.return_value = MagicMock()
                        mock_command.edit.return_value = MagicMock()
                        mock_command.commit.return_value = MagicMock()

                        responses = handler.submit_hra()

                        # Get the JSONResponse (last item) and parse its content
                        json_response = responses[-1]
                        # JSONResponse stores content as encoded bytes in 'content' attribute
                        response_data = json.loads(json_response.content.decode("utf-8"))
                        assert response_data["output_mode"] == "questionnaire"
                        assert response_data["success"] is True
