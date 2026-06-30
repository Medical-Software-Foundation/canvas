"""Tests for group_therapy.services.questionnaires."""

from unittest.mock import MagicMock, patch

from group_therapy.services import questionnaires as qn

_QN = "group_therapy.services.questionnaires"


def _opt(code, dbid, name):
    o = MagicMock()
    o.code, o.dbid, o.name = code, dbid, name
    return o


def _question(name, qtype, options=None):
    q = MagicMock()
    q.name, q.label, q.type = name, name + " label", qtype
    q.options = options or []
    q.add_response = MagicMock()
    return q


def _ro(mock):
    mock.TYPE_TEXT, mock.TYPE_INTEGER, mock.TYPE_RADIO, mock.TYPE_CHECKBOX = "TXT", "INT", "RAD", "CHK"


@patch(f"{_QN}.Questionnaire")
def test_list_questionnaires_maps_rows(mock_q):
    mock_q.objects.filter.return_value.values.return_value = [
        {"name": "MSE", "code": "QUES_0014", "code_system": "INTERNAL", "use_case_in_charting": "EXAM"},
    ]
    out = qn.list_questionnaires()
    assert out == [{"name": "MSE", "code": "QUES_0014", "code_system": "INTERNAL", "use_case": "EXAM"}]


@patch(f"{_QN}.Questionnaire")
def test_list_questionnaires_degrades_on_error(mock_q):
    mock_q.objects.filter.side_effect = AttributeError("boom")
    assert qn.list_questionnaires() == []


@patch(f"{_QN}.ResponseOption")
@patch(f"{_QN}.QuestionnaireCommand")
@patch(f"{_QN}.Questionnaire")
def test_question_schema_returns_questions_and_normalized_kind(mock_q, mock_cmd, mock_ro):
    _ro(mock_ro)
    mock_q.objects.filter.return_value.first.return_value = MagicMock(id="qid-1")
    mock_cmd.return_value.questions = [
        _question("q1", "RAD", [_opt("good", 1, "Good"), _opt("", 2, "Fair")]),
    ]
    schema = qn.question_schema("QUES_0014")
    assert schema[0]["name"] == "q1"
    assert schema[0]["kind"] == "radio"  # raw SDK type normalized for the renderer
    # code is the round-trip value; falls back to dbid when code is blank
    assert schema[0]["options"] == [{"value": "good", "label": "Good"}, {"value": "2", "label": "Fair"}]


@patch(f"{_QN}.Questionnaire")
def test_question_schema_empty_when_unresolved(mock_q):
    mock_q.objects.filter.return_value.first.return_value = None
    assert qn.question_schema("nope") == []


@patch(f"{_QN}.QuestionnaireCommand")
@patch(f"{_QN}.Questionnaire")
def test_question_schema_degrades_on_error(mock_q, mock_cmd):
    mock_q.objects.filter.return_value.first.return_value = MagicMock(id="qid-1")
    mock_cmd.side_effect = TypeError("boom")
    assert qn.question_schema("QUES_0014") == []


@patch(f"{_QN}.Questionnaire")
def test_build_command_none_when_unresolved(mock_q):
    mock_q.objects.filter.return_value.first.return_value = None
    assert qn.build_command("nope", "note-1", {"q1": "x"}) is None


@patch(f"{_QN}.Questionnaire")
def test_question_schema_degrades_when_resolve_raises(mock_q):
    mock_q.objects.filter.side_effect = ValueError("db boom")
    assert qn.question_schema("QUES_0014") == []


@patch(f"{_QN}.ResponseOption")
@patch(f"{_QN}.QuestionnaireCommand")
@patch(f"{_QN}.Questionnaire")
def test_build_command_checkbox_skips_unmatched_option(mock_q, mock_cmd, mock_ro):
    _ro(mock_ro)
    mock_q.objects.filter.return_value.first.return_value = MagicMock(id="qid-1")
    check_q = _question("c", "CHK", [_opt("a", 1, "A")])
    mock_cmd.return_value.questions = [check_q]
    qn.build_command("QUES_0014", "n", {"c": ["nomatch"]})
    # an unmatched checkbox value records nothing
    check_q.add_response.assert_not_called()


@patch(f"{_QN}.ResponseOption")
@patch(f"{_QN}.QuestionnaireCommand")
@patch(f"{_QN}.Questionnaire")
def test_build_command_ignores_unknown_question_type(mock_q, mock_cmd, mock_ro):
    _ro(mock_ro)
    mock_q.objects.filter.return_value.first.return_value = MagicMock(id="qid-1")
    unknown_q = _question("u", "WEIRD")
    mock_cmd.return_value.questions = [unknown_q]
    qn.build_command("QUES_0014", "n", {"u": "answered"})
    unknown_q.add_response.assert_not_called()  # falls through all type branches


@patch(f"{_QN}.QuestionnaireCommand")
@patch(f"{_QN}.Questionnaire")
def test_build_command_degrades_to_none_on_unsupported_question_type(mock_q, mock_cmd):
    # cmd.questions raises ValueError for an unsupported type -> degrade, no 500
    from unittest.mock import PropertyMock
    mock_q.objects.filter.return_value.first.return_value = MagicMock(id="qid-1")
    type(mock_cmd.return_value).questions = PropertyMock(
        side_effect=ValueError("Unsupported question type: WEIRD")
    )
    assert qn.build_command("QUES_0014", "n", {}) is None


@patch(f"{_QN}.ResponseOption")
@patch(f"{_QN}.QuestionnaireCommand")
@patch(f"{_QN}.Questionnaire")
def test_build_command_records_each_question_type(mock_q, mock_cmd, mock_ro):
    _ro(mock_ro)
    mock_q.objects.filter.return_value.first.return_value = MagicMock(id="qid-1")
    text_q = _question("t", "TXT")
    int_q = _question("i", "INT")
    radio_opts = [_opt("good", 1, "Good"), _opt("fair", 2, "Fair")]
    radio_q = _question("r", "RAD", radio_opts)
    check_opts = [_opt("a", 3, "A"), _opt("b", 4, "B")]
    check_q = _question("c", "CHK", check_opts)
    mock_cmd.return_value.questions = [text_q, int_q, radio_q, check_q]

    qn.build_command("QUES_0014", "note-9", {"t": "hello", "i": "42", "r": "fair", "c": ["a", "b"]})

    text_q.add_response.assert_called_once_with(text="hello")
    int_q.add_response.assert_called_once_with(integer=42)
    radio_q.add_response.assert_called_once_with(option=radio_opts[1])
    assert check_q.add_response.call_count == 2
    assert mock_cmd.return_value.note_uuid == "note-9"


@patch(f"{_QN}.ResponseOption")
@patch(f"{_QN}.QuestionnaireCommand")
@patch(f"{_QN}.Questionnaire")
def test_build_command_skips_empty_and_bad_values(mock_q, mock_cmd, mock_ro):
    _ro(mock_ro)
    mock_q.objects.filter.return_value.first.return_value = MagicMock(id="qid-1")
    empty_q = _question("e", "TXT")
    int_q = _question("i", "INT")
    radio_q = _question("r", "RAD", [_opt("good", 1, "Good")])
    mock_cmd.return_value.questions = [empty_q, int_q, radio_q]

    qn.build_command("QUES_0014", "n", {"e": "", "i": "notnum", "r": "missing"})

    empty_q.add_response.assert_not_called()   # blank answer skipped
    int_q.add_response.assert_not_called()     # non-integer skipped
    radio_q.add_response.assert_not_called()   # no matching option
