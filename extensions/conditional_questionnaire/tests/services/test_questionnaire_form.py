from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from conditional_questionnaire.services import questionnaire_form
from conditional_questionnaire.services.questionnaire_form import build_form

MODULE = "conditional_questionnaire.services.questionnaire_form"


class _Rel:
    """Stands in for a related manager: ``.all()`` returns the items."""

    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


def _option(dbid, name, ordering, status="AC"):
    return SimpleNamespace(
        dbid=dbid, name=name, code=name[:1], value=name.lower(), ordering=ordering, status=status
    )


def _condition(on, operator="=", option=None, value=None, status="AC"):
    return SimpleNamespace(
        dependent_on_id=on,
        operator=operator,
        answer_option_id=option,
        answer_value=value,
        status=status,
    )


def _question(dbid, kind="SING", options=(), conditions=(), behavior=None):
    option_set = SimpleNamespace(type=kind, options=_Rel(options)) if kind else None
    return SimpleNamespace(
        dbid=dbid,
        name=f"Q{dbid}",
        response_option_set=option_set,
        dependent_conditions=_Rel(conditions),
        enable_behavior=behavior,
    )


QUESTIONNAIRE = SimpleNamespace(id="qn-1", name="Intro")


def test_build_form_orders_and_filters_options():
    question = _question(
        1,
        options=[
            _option(3, "Later", 2),
            _option(2, "First", 1),
            _option(4, "Gone", 0, status="IN"),
        ],
    )
    form = build_form(QUESTIONNAIRE, [question])
    assert form["id"] == "qn-1"
    assert form["name"] == "Intro"
    assert form["saveable"] is True
    assert form["reason"] == ""
    field = form["questions"][0]
    assert field["id"] == 1
    assert field["type"] == "SING"
    assert [o["id"] for o in field["options"]] == [2, 3]
    assert field["options"][0] == {"id": 2, "name": "First", "code": "F", "value": "first"}
    assert field["rule"] is None


def test_question_without_option_set():
    form = build_form(QUESTIONNAIRE, [_question(1, kind=None)])
    assert form["questions"][0]["type"] == ""
    assert form["questions"][0]["options"] == []
    assert form["saveable"] is False


def test_unsupported_type_is_not_saveable():
    form = build_form(QUESTIONNAIRE, [_question(1, kind="DEC"), _question(2, kind="INT")])
    assert form["saveable"] is False
    assert "DEC" in form["reason"]
    assert "INT" not in form["reason"]


def test_rule_reads_conditions_and_behavior():
    root = _question(1)
    child = _question(
        2,
        kind="TXT",
        behavior="ALL",
        conditions=[
            _condition(1, "=", option=11),
            _condition(1, " Exists "),
            _condition(1, "!=", value=" no "),
        ],
    )
    rule = build_form(QUESTIONNAIRE, [root, child])["questions"][1]["rule"]
    assert rule == {
        "behavior": "all",
        "conditions": [
            {"on": 1, "op": "=", "option": 11, "value": None},
            {"on": 1, "op": "exists", "option": None, "value": None},
            {"on": 1, "op": "!=", "option": None, "value": "no"},
        ],
    }


def test_missing_behavior_reads_as_all():
    rule = build_form(
        QUESTIONNAIRE, [_question(1), _question(2, conditions=[_condition(1, "exists")])]
    )["questions"][1]["rule"]
    assert rule["behavior"] == "all"


def test_explicit_any_behavior_is_kept():
    rule = build_form(
        QUESTIONNAIRE,
        [_question(1), _question(2, conditions=[_condition(1, "exists")], behavior="ANY")],
    )["questions"][1]["rule"]
    assert rule["behavior"] == "any"


def test_unreadable_conditions_are_dropped():
    child = _question(
        2,
        conditions=[
            _condition(1, "exists", status="IN"),
            _condition(1, "contains"),
            _condition(1, None),
            _condition(99, "exists"),
            _condition(2, "exists"),
            _condition(1, "="),
            _condition(1, "!=", value="  "),
        ],
    )
    assert build_form(QUESTIONNAIRE, [_question(1), child])["questions"][1]["rule"] is None


def test_charting_questionnaires():
    with patch(f"{MODULE}.Questionnaire") as model:
        chain = model.objects.filter.return_value.order_by.return_value
        chain.values_list.return_value = [("id-a", "A"), ("id-b", "B")]
        result = questionnaire_form.charting_questionnaires()
    assert result == [{"id": "id-a", "name": "A"}, {"id": "id-b", "name": "B"}]
    model.objects.filter.assert_called_once_with(
        status="AC", can_originate_in_charting=True, use_case_in_charting="QUES"
    )
    model.objects.filter.return_value.order_by.assert_called_once_with("name")


def test_find_questionnaire():
    with patch(f"{MODULE}.Questionnaire") as model:
        model.objects.filter.return_value.first.return_value = QUESTIONNAIRE
        assert questionnaire_form.find_questionnaire("qn-1") is QUESTIONNAIRE
    model.objects.filter.assert_called_once_with(
        id="qn-1", status="AC", can_originate_in_charting=True, use_case_in_charting="QUES"
    )


def test_load_form_reads_the_question_map_in_order():
    first, second = _question(1), _question(2, kind="TXT")
    rows = [
        SimpleNamespace(question=first),
        SimpleNamespace(question=None),
        SimpleNamespace(question=second),
    ]
    questionnaire = MagicMock(id="qn-1")
    questionnaire.name = "Intro"
    questionnaire.questions.values_list.return_value = ["SING", "TXT"]
    with patch(f"{MODULE}.QuestionnaireQuestionMap") as model:
        queryset = MagicMock()
        model.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.order_by.return_value = queryset
        queryset.__iter__.return_value = iter(rows)
        form = questionnaire_form.load_form(questionnaire)
    assert [q["id"] for q in form["questions"]] == [1, 2]
    assert form["saveable"] is True
    model.objects.filter.assert_called_once_with(questionnaire=questionnaire, status="AC")
    questionnaire.questions.values_list.assert_called_once_with(
        "response_option_set__type", flat=True
    )


def test_inactive_linked_question_of_unsupported_type_blocks_save():
    form = build_form(QUESTIONNAIRE, [_question(1)], command_types={"SING", "DEC", ""})
    assert form["saveable"] is False
    assert "DEC" in form["reason"]
