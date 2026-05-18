"""Unit tests for the questionnaire-lookup helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from exam_chart_app.data.questionnaires import (
    find_questionnaires,
    get_questionnaire_detail,
)


def _mock_questionnaire(id="11111111-1111-1111-1111-111111111111", name="Standard ROS", code="ROS-STD", code_system="canvas"):
    # MagicMock's `name=` kwarg sets the mock's own repr-name, not an
    # attribute; explicit assignment is required for `.name` lookups to
    # return the intended string.
    q = MagicMock()
    q.id = id
    q.name = name
    q.code = code
    q.code_system = code_system
    return q


@patch("exam_chart_app.data.questionnaires.Questionnaire")
def test_find_questionnaires_ros_returns_name_matches(mock_q_cls):
    rows = [
        _mock_questionnaire(id="r1", name="Brief ROS"),
        _mock_questionnaire(id="r2", name="Standard ROS"),
    ]
    mock_q_cls.objects.filter.return_value.order_by.return_value = rows
    result = find_questionnaires("ros", secret_code=None)
    assert [r.name for r in result] == ["Brief ROS", "Standard ROS"]
    kwargs = mock_q_cls.objects.filter.call_args.kwargs
    assert kwargs.get("status") == "AC"


@patch("exam_chart_app.data.questionnaires.Questionnaire")
def test_find_questionnaires_pe_uses_different_name_pattern(mock_q_cls):
    mock_q_cls.objects.filter.return_value.order_by.return_value = []
    find_questionnaires("pe", secret_code=None)
    call_args = mock_q_cls.objects.filter.call_args
    q_args_str = str(call_args)
    assert "physical" in q_args_str.lower()


@patch("exam_chart_app.data.questionnaires.Questionnaire")
def test_find_questionnaires_secret_code_takes_precedence(mock_q_cls):
    pinned = _mock_questionnaire(id="custom", name="Custom ROS")
    mock_q_cls.objects.filter.return_value.first.return_value = pinned
    result = find_questionnaires("ros", secret_code="ROS-CUSTOM")
    assert result == [pinned]
    kwargs = mock_q_cls.objects.filter.call_args.kwargs
    assert kwargs.get("code") == "ROS-CUSTOM"


@patch("exam_chart_app.data.questionnaires.Questionnaire")
def test_find_questionnaires_secret_code_falls_through_when_not_found(mock_q_cls):
    fallback = _mock_questionnaire(id="r1", name="Standard ROS")
    mock_q_cls.objects.filter.side_effect = [
        MagicMock(first=MagicMock(return_value=None)),
        MagicMock(order_by=MagicMock(return_value=[fallback])),
    ]
    result = find_questionnaires("ros", secret_code="NOT-A-REAL-CODE")
    assert result == [fallback]


def test_find_questionnaires_unknown_kind_returns_empty():
    assert find_questionnaires("unknown_section", secret_code=None) == []


@patch("exam_chart_app.data.questionnaires.Questionnaire")
def test_get_questionnaire_detail_returns_questions(mock_q_cls):
    # MagicMock's `name=` constructor kwarg sets the mock's own repr-name,
    # not an attribute; assign explicitly after construction instead.
    option = MagicMock(pk=10, code="N", value="normal")
    option.name = "Normal"
    response_set = MagicMock(type="SING")
    response_set.options.all.return_value = [option]
    question = MagicMock(pk=42, code_system="LOINC", code="X")
    question.name = "Constitutional"
    question.response_option_set = response_set
    mock_q = _mock_questionnaire(id="11111111-1111-1111-1111-111111111111", name="Standard ROS")
    mock_q.questions.all.return_value = [question]
    # Helper now uses ``Questionnaire.objects.prefetch_related(...).get(id=...)``
    # to collapse the N+1 over questions × response_option_set × options; mock
    # the full chain.
    mock_q_cls.objects.prefetch_related.return_value.get.return_value = mock_q

    detail = get_questionnaire_detail("11111111-1111-1111-1111-111111111111")
    assert detail is not None
    assert detail["id"] == "11111111-1111-1111-1111-111111111111"
    assert detail["name"] == "Standard ROS"
    assert len(detail["questions"]) == 1
    q = detail["questions"][0]
    assert q["id"] == 42
    assert q["label"] == "Constitutional"
    assert q["type"] == "SING"
    assert q["options"] == [{"name": "Normal", "code": "N", "value": "normal"}]
    # Lock the prefetch chain so a future refactor that drops it (and
    # reintroduces the N+1) fails this test.
    mock_q_cls.objects.prefetch_related.assert_called_once_with(
        "questions__response_option_set__options",
    )


@patch("exam_chart_app.data.questionnaires.Questionnaire")
def test_get_questionnaire_detail_returns_none_on_missing(mock_q_cls):
    from canvas_sdk.v1.data import Questionnaire as _RealQuestionnaire
    mock_q_cls.DoesNotExist = _RealQuestionnaire.DoesNotExist
    mock_q_cls.objects.prefetch_related.return_value.get.side_effect = (
        _RealQuestionnaire.DoesNotExist
    )
    assert get_questionnaire_detail("missing") is None


@patch("exam_chart_app.data.questionnaires.Questionnaire")
def test_get_questionnaire_detail_returns_none_on_invalid_uuid_value_error(mock_q_cls):
    """Some Django UUID coercion paths raise ``ValueError`` on garbage input
    (e.g. legacy ``int()`` parsing). Still treated as a clean 404 so the
    handler returns ``{"error": "questionnaire not found"}``."""
    from canvas_sdk.v1.data import Questionnaire as _RealQuestionnaire
    mock_q_cls.DoesNotExist = _RealQuestionnaire.DoesNotExist
    mock_q_cls.objects.prefetch_related.return_value.get.side_effect = ValueError(
        "invalid literal for int() with base 16",
    )
    assert get_questionnaire_detail("not-a-uuid") is None


@patch("exam_chart_app.data.questionnaires.Questionnaire")
def test_get_questionnaire_detail_returns_none_on_validation_error(mock_q_cls):
    """``Questionnaire.id`` is a ``UUIDField`` — Django validates the value
    before the query runs and raises ``django.core.exceptions.ValidationError``
    when the input isn't a UUID. Pre-fix, that exception escaped the handler
    and triggered Django's traceback-formatter (∼48 MB allocation for
    locals/frames) on its way out as an empty-body 500. Lock the catch."""
    from django.core.exceptions import ValidationError
    from canvas_sdk.v1.data import Questionnaire as _RealQuestionnaire
    mock_q_cls.DoesNotExist = _RealQuestionnaire.DoesNotExist
    mock_q_cls.objects.prefetch_related.return_value.get.side_effect = ValidationError(
        "<one of the ROS ids from step 1> is not a valid UUID.",
    )
    assert get_questionnaire_detail("<one of the ROS ids from step 1>") is None


@patch("exam_chart_app.data.questionnaires.Questionnaire")
def test_find_questionnaires_pe_pattern_matches_exam_and_physical(mock_q_cls):
    """PE pattern should match 'Brief Exam', 'Standard Exam', 'Physical
    Exam' — i.e. any row whose name contains 'exam' or 'physical'."""
    mock_q_cls.objects.filter.return_value.order_by.return_value = []
    find_questionnaires("pe", secret_code=None)
    call_args = mock_q_cls.objects.filter.call_args
    q_args_str = str(call_args)
    assert "exam" in q_args_str.lower()
    assert "physical" in q_args_str.lower()
