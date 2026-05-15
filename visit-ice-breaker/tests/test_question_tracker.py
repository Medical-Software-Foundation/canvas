from unittest.mock import MagicMock, call, patch

from visit_ice_breaker.question_bank import Question
from visit_ice_breaker.question_tracker import QuestionTracker
from visit_ice_breaker.structures.age_group import AgeGroup


@patch("visit_ice_breaker.question_tracker.QuestionBank")
@patch("visit_ice_breaker.question_tracker.ShownQuestion")
def test_get_or_select_question(
    mock_model_cls: MagicMock,
    mock_question_bank_cls: MagicMock,
) -> None:
    def reset_mocks() -> None:
        mock_model_cls.reset_mock()
        mock_question_bank_cls.reset_mock()

    # existing question for the note is returned directly
    mock_existing: MagicMock = MagicMock()
    mock_existing.question_text = "What is your favorite food?"
    mock_existing.category = "Food & Cooking"
    mock_model_cls.objects.filter.return_value.first.side_effect = [mock_existing]

    result: Question = QuestionTracker.get_or_select_question(
        note_id="note-1", patient_id="patient-1", age_group=AgeGroup.KIDS
    )
    expected: Question = Question(category="Food & Cooking", text="What is your favorite food?")
    assert result == expected

    calls = [call.objects.filter(note_id="note-1"), call.objects.filter().first()]
    assert mock_model_cls.mock_calls == calls
    assert mock_question_bank_cls.mock_calls == []
    reset_mocks()

    # new note selects a fresh question and records it
    mock_model_cls.objects.filter.return_value.first.side_effect = [None]
    mock_model_cls.objects.filter.return_value.values_list.return_value = ["Already seen"]
    selected_question: Question = Question("Sports & Outdoors", "Do you play any sports?")
    mock_question_bank_cls.get_unused_question.side_effect = [selected_question]

    result = QuestionTracker.get_or_select_question(
        note_id="note-2", patient_id="patient-1", age_group=AgeGroup.TEENS
    )
    assert result == selected_question

    assert mock_question_bank_cls.get_unused_question.mock_calls == [
        call(AgeGroup.TEENS, ["Already seen"]),
    ]
    mock_model_cls.objects.create.assert_called_once_with(
        note_id="note-2",
        patient_id="patient-1",
        question_text="Do you play any sports?",
        category="Sports & Outdoors",
    )
    reset_mocks()


@patch("visit_ice_breaker.question_tracker.ShownQuestion")
def test_get_shown_questions(mock_model_cls: MagicMock) -> None:
    def reset_mocks() -> None:
        mock_model_cls.reset_mock()

    # patient with existing history
    mock_model_cls.objects.filter.return_value.values_list.return_value = ["q1", "q2"]

    result: list[str] = QuestionTracker._get_shown_questions("patient-1")
    expected: list[str] = ["q1", "q2"]
    assert result == expected

    calls = [
        call.objects.filter(patient_id="patient-1"),
        call.objects.filter().values_list("question_text", flat=True),
    ]
    assert mock_model_cls.mock_calls == calls
    reset_mocks()

    # patient with no history returns empty list
    mock_model_cls.objects.filter.return_value.values_list.return_value = []

    result = QuestionTracker._get_shown_questions("patient-new")
    assert result == []
    reset_mocks()
