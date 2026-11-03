from types import SimpleNamespace
from unittest.mock import MagicMock

from charting_tools.questionnaires import key_for, needs_questionnaire, options_by_command, resolve

MODULE = "charting_tools.questionnaires"


def test_needs_questionnaire() -> None:
    assert all(needs_questionnaire(k) for k in ("questionnaire", "ros", "exam", "structuredAssessment"))
    assert needs_questionnaire("hpi") is False


def test_key_for() -> None:
    assert key_for("ros", {"code_system": "LOINC", "code": "123"}) == ("ROS", "LOINC", "123")
    assert key_for("ros", {"code_system": "LOINC", "code": ""}) is None
    assert key_for("ros", None) is None


def test_options_grouped_by_command(mocker: MagicMock) -> None:
    query = mocker.patch(f"{MODULE}.Questionnaire.objects.filter")
    query.return_value.exclude.return_value.order_by.return_value.values.return_value = [
        {"name": "GAD-7", "code_system": "LOINC", "code": "69737-5", "use_case_in_charting": "QUES", "carry_forward": "off"},
        {"name": "Standard ROS", "code_system": "INTERNAL", "code": "ros1", "use_case_in_charting": "ROS", "carry_forward": "all"},
    ]
    options = options_by_command()

    assert query.call_args.kwargs["status"] == "AC"
    assert query.call_args.kwargs["can_originate_in_charting"] is True
    assert set(query.call_args.kwargs["use_case_in_charting__in"]) == {"QUES", "ROS", "EXAM", "SA"}
    query.return_value.exclude.assert_called_once_with(code="")
    assert options == {
        "questionnaire": [{"name": "GAD-7", "code_system": "LOINC", "code": "69737-5", "carry_forward": "off"}],
        "ros": [{"name": "Standard ROS", "code_system": "INTERNAL", "code": "ros1", "carry_forward": "all"}],
        "exam": [],
        "structuredAssessment": [],
    }


def _q(dbid: int, use_case: str, system: str, code: str) -> SimpleNamespace:
    return SimpleNamespace(dbid=dbid, id=f"q{dbid}", use_case_in_charting=use_case, code_system=system, code=code)


def test_resolve_matches_exact_key_and_prefers_newest(mocker: MagicMock) -> None:
    query = mocker.patch(f"{MODULE}.Questionnaire.objects.filter")
    query.return_value.order_by.return_value = [
        _q(9, "QUES", "LOINC", "1"),  # newest active version
        _q(3, "QUES", "LOINC", "1"),
        _q(8, "QUES", "OTHER", "1"),  # same code, other system: not requested
        _q(7, "EXAM", "LOINC", "1"),  # same code, other use case: not requested
    ]
    found = resolve({("QUES", "LOINC", "1"), ("ROS", "LOINC", "2")})
    query.return_value.order_by.assert_called_once_with("-dbid")
    assert {k: v.id for k, v in found.items()} == {("QUES", "LOINC", "1"): "q9"}


def test_resolve_empty_skips_query(mocker: MagicMock) -> None:
    query = mocker.patch(f"{MODULE}.Questionnaire.objects.filter")
    assert resolve(set()) == {}
    query.assert_not_called()
