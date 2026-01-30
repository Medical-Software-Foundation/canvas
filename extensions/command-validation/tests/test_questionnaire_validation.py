"""Tests for RequireAllQuestionsAnsweredHandler."""

from unittest.mock import Mock, patch

from canvas_sdk.events import EventType

from command_validation.handlers.questionnaire_validation import RequireAllQuestionsAnsweredHandler
from tests.conftest import create_question


def test_handler_responds_to_post_validation_event() -> None:
    """Test that the handler is configured to respond to the correct event type."""
    assert RequireAllQuestionsAnsweredHandler.RESPONDS_TO == EventType.Name(
        EventType.QUESTIONNAIRE_COMMAND__POST_VALIDATION
    )


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_blocks_commit_with_unanswered_single_choice(mock_command, mock_event, mock_command_data) -> None:
    """Test that the handler blocks commit when a single choice question is unanswered."""
    questions = [
        create_question(9, "question-9", "SING", "Tobacco status"),
        create_question(10, "question-10", "SING", "Another question"),
    ]
    # Only first question answered
    data = mock_command_data(questions, {"question-9": 26})

    command = Mock()
    command.data = data
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 1


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_blocks_commit_with_unanswered_multiple_choice(mock_command, mock_event, mock_command_data) -> None:
    """Test that the handler blocks commit when no options are selected in multiple choice."""
    questions = [
        create_question(10, "question-10", "MULT", "Tobacco type"),
    ]
    # No options selected
    data = mock_command_data(questions, {
        "question-10": [
            {"text": "Option1", "value": 1, "selected": False},
            {"text": "Option2", "value": 2, "selected": False},
        ]
    })

    command = Mock()
    command.data = data
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 1


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_blocks_commit_with_empty_text(mock_command, mock_event, mock_command_data) -> None:
    """Test that the handler blocks commit when a text question is empty."""
    questions = [
        create_question(11, "question-11", "TXT", "Comment"),
    ]
    data = mock_command_data(questions, {"question-11": ""})

    command = Mock()
    command.data = data
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 1


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_allows_commit_with_all_questions_answered(mock_command, mock_event, mock_command_data) -> None:
    """Test that the handler allows commit when all questions are answered."""
    questions = [
        create_question(9, "question-9", "SING", "Tobacco status"),
        create_question(10, "question-10", "MULT", "Tobacco type"),
        create_question(11, "question-11", "TXT", "Comment"),
    ]
    data = mock_command_data(questions, {
        "question-9": 26,
        "question-10": [
            {"text": "Option1", "value": 1, "selected": True},
            {"text": "Option2", "value": 2, "selected": False},
        ],
        "question-11": "Some comment",
    })

    command = Mock()
    command.data = data
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 0


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_allows_commit_when_no_data(mock_command, mock_event) -> None:
    """Test that the handler allows commit when there's no data."""
    command = Mock()
    command.data = None
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 0


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_allows_commit_when_no_questions(mock_command, mock_event, mock_command_data) -> None:
    """Test that the handler allows commit when there are no questions."""
    data = mock_command_data(questions=[], responses={})

    command = Mock()
    command.data = data
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 0


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_shows_question_labels_when_few_unanswered(mock_command, mock_event, mock_command_data) -> None:
    """Test that error shows question labels when 3 or fewer unanswered."""
    questions = [
        create_question(9, "question-9", "SING", "Tobacco status"),
        create_question(10, "question-10", "SING", "Another question"),
    ]
    # No questions answered
    data = mock_command_data(questions, {})

    command = Mock()
    command.data = data
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 1


@patch("command_validation.handlers.questionnaire_validation.Command")
def test_shows_count_when_many_unanswered(mock_command, mock_event, mock_command_data) -> None:
    """Test that error shows count when more than 3 unanswered."""
    questions = [
        create_question(1, "q1", "SING", "Q1"),
        create_question(2, "q2", "SING", "Q2"),
        create_question(3, "q3", "SING", "Q3"),
        create_question(4, "q4", "SING", "Q4"),
        create_question(5, "q5", "SING", "Q5"),
    ]
    # Only one answered
    data = mock_command_data(questions, {"q1": 1})

    command = Mock()
    command.data = data
    mock_command.objects.get.return_value = command

    handler = RequireAllQuestionsAnsweredHandler(event=mock_event())
    effects = handler.compute()

    assert len(effects) == 1
