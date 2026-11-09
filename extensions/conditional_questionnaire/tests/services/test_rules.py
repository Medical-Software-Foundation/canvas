from conditional_questionnaire.services.rules import (
    condition_met,
    has_answer,
    is_shown,
    visible_answers,
)


def _q(qid, rule=None, options=None, kind="SING"):
    return {"id": qid, "name": f"Q{qid}", "type": kind, "options": options or [], "rule": rule}


def _rule(*conditions, behavior="any"):
    return {"behavior": behavior, "conditions": list(conditions)}


def _cond(on, op, option=None, value=None):
    return {"on": on, "op": op, "option": option, "value": value}


YES_NO = [
    {"id": 11, "name": "Yes", "code": "Y", "value": "yes"},
    {"id": 12, "name": "No", "code": "N", "value": "no"},
]


def test_has_answer():
    assert not has_answer(None)
    assert not has_answer("  ")
    assert not has_answer([])
    assert has_answer("x")
    assert has_answer(["11"])
    assert has_answer(0)


def test_exists_and_not_exists():
    assert condition_met(_cond(1, "exists"), {"1": "a"}, {})
    assert not condition_met(_cond(1, "exists"), {}, {})
    assert condition_met(_cond(1, "not_exists"), {"1": ""}, {})
    assert not condition_met(_cond(1, "not_exists"), {"1": "a"}, {})


def test_equals_option():
    assert condition_met(_cond(1, "=", option=11), {"1": "11"}, {})
    assert not condition_met(_cond(1, "=", option=11), {"1": "12"}, {})


def test_equals_and_not_equals_need_an_answer():
    assert not condition_met(_cond(1, "=", option=11), {}, {})
    assert not condition_met(_cond(1, "!=", option=11), {}, {})


def test_not_equals_option():
    assert condition_met(_cond(1, "!=", option=11), {"1": "12"}, {})
    assert not condition_met(_cond(1, "!=", option=11), {"1": "11"}, {})


def test_equals_option_in_multi_select():
    assert condition_met(_cond(1, "=", option=11), {"1": ["12", "11"]}, {})
    assert not condition_met(_cond(1, "!=", option=11), {"1": ["12", "11"]}, {})


def test_value_matches_option_name_code_or_value_ignoring_case():
    by_id = {"1": _q(1, options=YES_NO)}
    assert condition_met(_cond(1, "=", value="YES"), {"1": "11"}, by_id)
    assert condition_met(_cond(1, "=", value="y"), {"1": "11"}, by_id)
    assert not condition_met(_cond(1, "=", value="no"), {"1": "11"}, by_id)
    assert condition_met(_cond(1, "!=", value="no"), {"1": "11"}, by_id)
    assert condition_met(_cond(1, "=", value="No"), {"1": "12"}, by_id)


def test_value_matches_free_text():
    by_id = {"1": _q(1, kind="TXT")}
    assert condition_met(_cond(1, "=", value="Chest pain"), {"1": " chest PAIN "}, by_id)
    assert not condition_met(_cond(1, "=", value="Chest pain"), {"1": "other"}, by_id)


def test_is_shown_without_rule():
    assert is_shown(_q(1), {}, {})
    assert is_shown(_q(1, rule={"behavior": "all", "conditions": []}), {}, {})


def test_all_and_any():
    rule_all = _rule(_cond(1, "exists"), _cond(2, "exists"), behavior="all")
    rule_any = _rule(_cond(1, "exists"), _cond(2, "exists"), behavior="any")
    assert not is_shown(_q(3, rule_all), {"1": "a"}, {})
    assert is_shown(_q(3, rule_all), {"1": "a", "2": "b"}, {})
    assert is_shown(_q(3, rule_any), {"1": "a"}, {})
    assert not is_shown(_q(3, rule_any), {}, {})


def test_chain_collapses_when_the_root_changes():
    questions = [
        _q(1, options=YES_NO),
        _q(2, _rule(_cond(1, "=", option=11)), kind="TXT"),
        _q(3, _rule(_cond(2, "exists")), kind="TXT"),
        _q(4, kind="TXT"),
    ]
    answers = {"1": "12", "2": "stale", "3": "also stale", "4": "kept"}
    assert visible_answers(questions, answers) == {"1": "12", "4": "kept"}


def test_chain_kept_when_the_root_holds():
    questions = [
        _q(1, options=YES_NO),
        _q(2, _rule(_cond(1, "=", option=11)), kind="TXT"),
        _q(3, _rule(_cond(2, "exists")), kind="TXT"),
    ]
    answers = {"1": "11", "2": "a", "3": "b"}
    assert visible_answers(questions, answers) == answers


def test_condition_on_a_later_question():
    questions = [
        _q(1, _rule(_cond(3, "=", option=11)), kind="TXT"),
        _q(2, _rule(_cond(1, "exists")), kind="TXT"),
        _q(3, options=YES_NO),
    ]
    assert visible_answers(questions, {"1": "a", "2": "b", "3": "12"}) == {"3": "12"}


def test_blank_answers_are_dropped():
    assert visible_answers([_q(1, kind="TXT")], {"1": "  ", "2": []}) == {}


def test_not_exists_shows_until_answered():
    questions = [_q(1, kind="TXT"), _q(2, _rule(_cond(1, "not_exists")), kind="TXT")]
    assert visible_answers(questions, {"2": "x"}) == {"2": "x"}
    assert visible_answers(questions, {"1": "a", "2": "x"}) == {"1": "a"}
