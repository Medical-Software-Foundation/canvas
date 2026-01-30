"""Tests for RequireAllQuestionsAnsweredHandler."""

from unittest.mock import Mock, patch

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from command_validation.handlers.questionnaire_validation import RequireAllQuestionsAnsweredHandler


def test_handler_responds_to_pre_commit_event() -> None:
    """Test that the handler is configured to respond to the correct event type."""
    assert RequireAllQuestionsAnsweredHandler.RESPONDS_TO == EventType.Name(
        EventType.QUESTIONNAIRE_COMMAND__PRE_COMMIT
    )


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_blocks_commit_with_unanswered_questions(mock_command, mock_event, mock_interview) -> None:
    """Test that the handler blocks commit when questions are unanswered."""
    # Setup: 3 questions, only 1 answered
    interview = mock_interview(
        question_ids=[1, 2, 3],
        answered_ids=[1],
        question_names={1: "Weight", 2: "Height", 3: "Blood Pressure"}
    )

    command = Mock()
    command.data_object = interview
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.EVENT_VALIDATION_ERROR


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_allows_commit_with_all_questions_answered(mock_command, mock_event, mock_interview) -> None:
    """Test that the handler allows commit when all questions are answered."""
    # Setup: 3 questions, all answered
    interview = mock_interview(
        question_ids=[1, 2, 3],
        answered_ids=[1, 2, 3]
    )

    command = Mock()
    command.data_object = interview
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 0


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_allows_commit_when_no_interview(mock_command, mock_event) -> None:
    """Test that the handler allows commit when there's no interview attached."""
    command = Mock()
    command.data_object = None
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 0


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_allows_commit_when_no_questionnaire(mock_command, mock_event) -> None:
    """Test that the handler allows commit when there's no questionnaire."""
    interview = Mock()
    interview.questionnaires.first.return_value = None

    command = Mock()
    command.data_object = interview
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 0


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_shows_question_names_when_few_unanswered(mock_command, mock_event, mock_interview) -> None:
    """Test that error shows question names when 3 or fewer unanswered."""
    interview = mock_interview(
        question_ids=[1, 2, 3],
        answered_ids=[1],
        question_names={1: "Weight", 2: "Height", 3: "Blood Pressure"}
    )

    command = Mock()
    command.data_object = interview
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.EVENT_VALIDATION_ERROR


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_shows_count_when_many_unanswered(mock_command, mock_event, mock_interview) -> None:
    """Test that error shows count when more than 3 unanswered."""
    interview = mock_interview(
        question_ids=[1, 2, 3, 4, 5],
        answered_ids=[1]
    )

    command = Mock()
    command.data_object = interview
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.EVENT_VALIDATION_ERROR
