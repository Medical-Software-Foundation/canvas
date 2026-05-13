# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.
# If you want to modify which files are used for testing, check the [tool.pytest.ini_options] section in pyproject.toml.

import uuid
from unittest.mock import MagicMock, Mock, patch

from canvas_sdk.commands import QuestionnaireCommand
from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import PatientFactory

from phq9_madrs_workflow.protocols.phq9_madrs_workflow import Protocol


def create_mock_interview(questionnaire_name: str, responses: list[int]):
    """Create a mock interview with specified questionnaire name and response values."""
    mock_interview = MagicMock()
    mock_interview.committer = MagicMock()

    # Mock questionnaire
    mock_questionnaire = MagicMock()
    mock_questionnaire.name = questionnaire_name
    mock_questionnaire.id = f"{questionnaire_name.lower()}-id"
    mock_interview.questionnaires.all.return_value = [mock_questionnaire]

    # Mock interview responses
    mock_responses = []
    for value in responses:
        mock_response = MagicMock()
        mock_response.response_option.value = str(value)
        mock_responses.append(mock_response)

    # Mock select_related to support the optimized query
    mock_queryset = MagicMock()
    mock_queryset.all.return_value = mock_responses
    mock_interview.interview_responses.select_related.return_value = mock_queryset

    return mock_interview


def test_phq9_score_20_or_below_triggers_madrs():
    """Test that PHQ-9 with score ≤ 20 triggers MADRS origination."""
    # Arrange
    mock_event = MagicMock()
    mock_event.target.id = "command-123"
    mock_event.context = {"note": {"uuid": str(uuid.uuid4())}}

    protocol = Protocol(event=mock_event)

    # Mock command and interview
    mock_command = MagicMock()
    mock_interview = create_mock_interview("PHQ-9", [2, 2, 2, 2, 2, 2, 2, 2, 2])  # Score = 18
    mock_command.anchor_object = mock_interview

    # Mock MADRS questionnaire
    mock_madrs = MagicMock()
    mock_madrs.id = uuid.uuid4()
    mock_madrs.name = "MADRS - Depression Screening"
    mock_madrs.status = "active"

    # Mock the originate effect
    mock_effect = MagicMock()
    mock_effect.type = EffectType.ORIGINATE_QUESTIONNAIRE_COMMAND

    with patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.Command") as MockCommand, \
         patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.Questionnaire") as MockQuestionnaire, \
         patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.QuestionnaireCommand") as MockQuestionnaireCommand:
        MockCommand.objects.get.return_value = mock_command
        MockQuestionnaire.objects.filter.return_value.all.return_value = [mock_madrs]

        # Mock the QuestionnaireCommand instance
        mock_questionnaire_command = MagicMock()
        mock_questionnaire_command.originate.return_value = mock_effect
        MockQuestionnaireCommand.return_value = mock_questionnaire_command

        # Act
        effects = protocol.compute()

        # Assert
        assert len(effects) == 1
        assert effects[0].type == EffectType.ORIGINATE_QUESTIONNAIRE_COMMAND
        # Verify that QuestionnaireCommand was created with correct parameters
        MockQuestionnaireCommand.assert_called_once()
        call_kwargs = MockQuestionnaireCommand.call_args[1]
        assert call_kwargs["questionnaire_id"] == str(mock_madrs.id)


def test_phq9_score_above_20_does_not_trigger_madrs():
    """Test that PHQ-9 with score > 20 does not trigger MADRS."""
    # Arrange
    mock_event = MagicMock()
    mock_event.target.id = "command-123"
    mock_event.context = {"note": {"uuid": "note-456"}}

    protocol = Protocol(event=mock_event)

    # Mock command and interview with high score
    mock_command = MagicMock()
    mock_interview = create_mock_interview("PHQ-9", [3, 3, 3, 3, 3, 3, 3])  # Score = 21
    mock_command.anchor_object = mock_interview

    with patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.Command") as MockCommand:
        MockCommand.objects.get.return_value = mock_command

        # Act
        effects = protocol.compute()

        # Assert
        assert len(effects) == 0


def test_madrs_commit_adds_comment_with_normal_interpretation():
    """Test that MADRS commit with score 0-6 adds questionnaire result with 'Normal/No depression'."""
    # Arrange
    mock_event = MagicMock()
    mock_event.target.id = "command-123"
    mock_event.context = {"note": {"uuid": "note-456"}}

    protocol = Protocol(event=mock_event)

    # Mock command and interview
    mock_command = MagicMock()
    mock_interview = create_mock_interview("MADRS", [0, 1, 0, 1, 2, 1, 0, 0, 0, 0])  # Score = 5
    mock_interview.id = uuid.uuid4()
    mock_command.anchor_object = mock_interview

    with patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.Command") as MockCommand:
        MockCommand.objects.get.return_value = mock_command

        # Act
        effects = protocol.compute()

        # Assert
        assert len(effects) == 1
        assert effects[0].type == EffectType.CREATE_QUESTIONNAIRE_RESULT


def test_madrs_commit_adds_comment_with_mild_interpretation():
    """Test that MADRS commit with score 7-19 adds questionnaire result with 'Mild depression'."""
    # Arrange
    mock_event = MagicMock()
    mock_event.target.id = "command-123"
    mock_event.context = {"note": {"uuid": "note-456"}}

    protocol = Protocol(event=mock_event)

    # Mock command and interview
    mock_command = MagicMock()
    mock_interview = create_mock_interview("MADRS", [1, 2, 1, 2, 2, 2, 1, 1, 1, 2])  # Score = 15
    mock_interview.id = uuid.uuid4()
    mock_command.anchor_object = mock_interview

    with patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.Command") as MockCommand:
        MockCommand.objects.get.return_value = mock_command

        # Act
        effects = protocol.compute()

        # Assert
        assert len(effects) == 1
        assert effects[0].type == EffectType.CREATE_QUESTIONNAIRE_RESULT


def test_madrs_commit_adds_comment_with_moderate_interpretation():
    """Test that MADRS commit with score 20-34 adds questionnaire result with 'Moderate depression'."""
    # Arrange
    mock_event = MagicMock()
    mock_event.target.id = "command-123"
    mock_event.context = {"note": {"uuid": "note-456"}}

    protocol = Protocol(event=mock_event)

    # Mock command and interview
    mock_command = MagicMock()
    mock_interview = create_mock_interview("MADRS", [2, 3, 2, 3, 2, 3, 2, 2, 3, 3])  # Score = 25
    mock_interview.id = uuid.uuid4()
    mock_command.anchor_object = mock_interview

    with patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.Command") as MockCommand:
        MockCommand.objects.get.return_value = mock_command

        # Act
        effects = protocol.compute()

        # Assert
        assert len(effects) == 1
        assert effects[0].type == EffectType.CREATE_QUESTIONNAIRE_RESULT


def test_madrs_commit_adds_comment_with_severe_interpretation():
    """Test that MADRS commit with score 35-60 adds questionnaire result with 'Severe depression'."""
    # Arrange
    mock_event = MagicMock()
    mock_event.target.id = "command-123"
    mock_event.context = {"note": {"uuid": "note-456"}}

    protocol = Protocol(event=mock_event)

    # Mock command and interview
    mock_command = MagicMock()
    mock_interview = create_mock_interview("MADRS", [4, 4, 4, 4, 4, 4, 4, 4, 4, 4])  # Score = 40
    mock_interview.id = uuid.uuid4()
    mock_command.anchor_object = mock_interview

    with patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.Command") as MockCommand:
        MockCommand.objects.get.return_value = mock_command

        # Act
        effects = protocol.compute()

        # Assert
        assert len(effects) == 1
        assert effects[0].type == EffectType.CREATE_QUESTIONNAIRE_RESULT


def test_uncommitted_interview_returns_no_effects():
    """Test that an uncommitted interview returns no effects."""
    # Arrange
    mock_event = MagicMock()
    mock_event.target.id = "command-123"
    mock_event.context = {"note": {"uuid": "note-456"}}

    protocol = Protocol(event=mock_event)

    # Mock command with uncommitted interview
    mock_command = MagicMock()
    mock_interview = MagicMock()
    mock_interview.committer = None  # Uncommitted
    mock_command.anchor_object = mock_interview

    with patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.Command") as MockCommand:
        MockCommand.objects.get.return_value = mock_command

        # Act
        effects = protocol.compute()

        # Assert
        assert len(effects) == 0


def test_unknown_questionnaire_returns_no_effects():
    """Test that an unknown questionnaire type returns no effects."""
    # Arrange
    mock_event = MagicMock()
    mock_event.target.id = "command-123"
    mock_event.context = {"note": {"uuid": "note-456"}}

    protocol = Protocol(event=mock_event)

    # Mock command and interview with unknown questionnaire
    mock_command = MagicMock()
    mock_interview = create_mock_interview("Some Other Questionnaire", [1, 2, 3])
    mock_command.anchor_object = mock_interview

    with patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.Command") as MockCommand:
        MockCommand.objects.get.return_value = mock_command

        # Act
        effects = protocol.compute()

        # Assert
        assert len(effects) == 0


def test_score_calculation_handles_invalid_values():
    """Test that score calculation handles invalid response values gracefully."""
    # Arrange
    mock_event = MagicMock()
    mock_event.target.id = "command-123"
    mock_event.context = {"note": {"uuid": "note-456"}}

    protocol = Protocol(event=mock_event)

    # Mock command and interview with invalid response values
    mock_command = MagicMock()
    mock_interview = MagicMock()
    mock_interview.committer = MagicMock()
    mock_interview.id = uuid.uuid4()

    mock_questionnaire = MagicMock()
    mock_questionnaire.name = "MADRS"
    mock_interview.questionnaires.all.return_value = [mock_questionnaire]

    # Create responses with one invalid value
    mock_response1 = MagicMock()
    mock_response1.response_option.value = "2"
    mock_response2 = MagicMock()
    mock_response2.response_option.value = "invalid"
    mock_response3 = MagicMock()
    mock_response3.response_option.value = "3"

    # Mock select_related to return the same queryset
    mock_queryset = MagicMock()
    mock_queryset.all.return_value = [mock_response1, mock_response2, mock_response3]
    mock_interview.interview_responses.select_related.return_value = mock_queryset
    mock_command.anchor_object = mock_interview

    with patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.Command") as MockCommand:
        MockCommand.objects.get.return_value = mock_command

        # Act
        effects = protocol.compute()

        # Assert - Should still work with valid values (2 + 3 = 5)
        assert len(effects) == 1
        assert effects[0].type == EffectType.CREATE_QUESTIONNAIRE_RESULT


def test_madrs_fallback_to_first_match_when_no_exact_name():
    """Test that MADRS lookup falls back to first match when no exact name match."""
    # Arrange
    mock_event = MagicMock()
    mock_event.target.id = "command-123"
    mock_event.context = {"note": {"uuid": str(uuid.uuid4())}}

    protocol = Protocol(event=mock_event)

    # Mock command and interview
    mock_command = MagicMock()
    mock_interview = create_mock_interview("PHQ-9", [2, 2, 2, 2, 2, 2, 2, 2, 2])  # Score = 18
    mock_command.anchor_object = mock_interview

    # Mock MADRS questionnaires - multiple but none with exact name
    mock_madrs1 = MagicMock()
    mock_madrs1.id = uuid.uuid4()
    mock_madrs1.name = "MADRS - Depression Screening (v2)"  # Not exact match
    mock_madrs1.status = "active"

    mock_madrs2 = MagicMock()
    mock_madrs2.id = uuid.uuid4()
    mock_madrs2.name = "MADRS Depression Assessment"  # Not exact match
    mock_madrs2.status = "active"

    # Mock the originate effect
    mock_effect = MagicMock()
    mock_effect.type = EffectType.ORIGINATE_QUESTIONNAIRE_COMMAND

    with patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.Command") as MockCommand, \
         patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.Questionnaire") as MockQuestionnaire, \
         patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.QuestionnaireCommand") as MockQuestionnaireCommand:
        MockCommand.objects.get.return_value = mock_command
        # Return multiple MADRS, none with exact name
        MockQuestionnaire.objects.filter.return_value.all.return_value = [mock_madrs1, mock_madrs2]

        # Mock the QuestionnaireCommand instance
        mock_questionnaire_command = MagicMock()
        mock_questionnaire_command.originate.return_value = mock_effect
        MockQuestionnaireCommand.return_value = mock_questionnaire_command

        # Act
        effects = protocol.compute()

        # Assert - should use first match
        assert len(effects) == 1
        assert effects[0].type == EffectType.ORIGINATE_QUESTIONNAIRE_COMMAND
        call_kwargs = MockQuestionnaireCommand.call_args[1]
        assert call_kwargs["questionnaire_id"] == str(mock_madrs1.id)  # Should use first one


def test_madrs_out_of_range_score():
    """Test that MADRS commit with out-of-range score is handled."""
    # Arrange
    mock_event = MagicMock()
    mock_event.target.id = "command-123"
    mock_event.context = {"note": {"uuid": "note-456"}}

    protocol = Protocol(event=mock_event)

    # Mock command and interview with very high score (> 60)
    mock_command = MagicMock()
    mock_interview = create_mock_interview("MADRS", [6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 10])  # Score = 70
    mock_interview.id = uuid.uuid4()
    mock_command.anchor_object = mock_interview

    with patch("phq9_madrs_workflow.protocols.phq9_madrs_workflow.Command") as MockCommand:
        MockCommand.objects.get.return_value = mock_command

        # Act
        effects = protocol.compute()

        # Assert - Should still create result with out-of-range message
        assert len(effects) == 1
        assert effects[0].type == EffectType.CREATE_QUESTIONNAIRE_RESULT
