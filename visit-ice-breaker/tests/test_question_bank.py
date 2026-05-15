from unittest.mock import patch

from visit_ice_breaker.question_bank import Question, QuestionBank
from visit_ice_breaker.structures.age_group import AgeGroup


def test_questions_coverage() -> None:
    for age_group in AgeGroup:
        questions: list[Question] = QuestionBank.QUESTIONS[age_group]
        assert len(questions) > 0, f"No questions for {age_group}"


@patch("visit_ice_breaker.question_bank.random")
def test_get_random_question(mock_random) -> None:  # type: ignore[no-untyped-def]
    def reset_mocks() -> None:
        mock_random.reset_mock()

    tests = [
        (AgeGroup.KIDS, 0),
        (AgeGroup.TEENS, 2),
        (AgeGroup.ADULTS, 1),
        (AgeGroup.SENIORS, 3),
    ]
    for age_group, index in tests:
        expected: Question = QuestionBank.QUESTIONS[age_group][index]
        mock_random.choice.side_effect = [expected]

        result: Question = QuestionBank.get_random_question(age_group)
        assert result == expected

        calls = [((QuestionBank.QUESTIONS[age_group],),)]
        assert mock_random.choice.mock_calls == [calls[0]]
        reset_mocks()


@patch("visit_ice_breaker.question_bank.random")
def test_get_unused_question(mock_random) -> None:  # type: ignore[no-untyped-def]
    def reset_mocks() -> None:
        mock_random.reset_mock()

    all_kids: list[Question] = QuestionBank.QUESTIONS[AgeGroup.KIDS]

    # no shown questions returns from full pool
    mock_random.choice.side_effect = [all_kids[0]]
    result: Question = QuestionBank.get_unused_question(AgeGroup.KIDS, [])
    assert result == all_kids[0]
    mock_random.choice.assert_called_once_with(all_kids)
    reset_mocks()

    # shown questions are filtered out
    shown: list[str] = [all_kids[0].text, all_kids[1].text]
    expected_available: list[Question] = [q for q in all_kids if q.text not in shown]
    mock_random.choice.side_effect = [expected_available[0]]
    result = QuestionBank.get_unused_question(AgeGroup.KIDS, shown)
    assert result == expected_available[0]
    mock_random.choice.assert_called_once_with(expected_available)
    reset_mocks()

    # all questions exhausted resets to full pool
    all_shown: list[str] = [q.text for q in all_kids]
    mock_random.choice.side_effect = [all_kids[0]]
    result = QuestionBank.get_unused_question(AgeGroup.KIDS, all_shown)
    assert result == all_kids[0]
    mock_random.choice.assert_called_once_with(all_kids)
    reset_mocks()
