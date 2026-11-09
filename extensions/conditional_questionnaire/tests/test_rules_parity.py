"""The Field Rules are written twice: ``services/rules.py`` (authoritative, on save) and
the JavaScript in ``templates/form.html`` (live show and hide). These tests cut the
shipped JS rule block out of the template, run it in node, and check it gives the same
answers and the same shown/hidden questions as the Python for every case below.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conditional_questionnaire.services.rules import is_shown, visible_answers

TEMPLATE = (
    Path(__file__).resolve().parent.parent / "conditional_questionnaire" / "templates" / "form.html"
).read_text()
START = "// ---- Field Rules: mirrors services/rules.py"
END = "// ---- end Field Rules"

NODE = shutil.which("node")

YES_NO = [
    {"id": 11, "name": "Yes", "code": "Y", "value": "yes"},
    {"id": 12, "name": "No", "code": "N", "value": "no"},
]
PICKS = [
    {"id": 21, "name": "Reviewed chart", "code": "R", "value": "reviewed"},
    {"id": 22, "name": "Confirmed phone", "code": "P", "value": "phone"},
]


def _q(qid, rule=None, options=None, kind="SING"):
    return {"id": qid, "name": f"Q{qid}", "type": kind, "options": options or [], "rule": rule}


def _rule(*conditions, behavior="any"):
    return {"behavior": behavior, "conditions": list(conditions)}


def _cond(on, op, option=None, value=None):
    return {"on": on, "op": op, "option": option, "value": value}


CHAIN = [
    _q(1, options=YES_NO),
    _q(2, _rule(_cond(1, "=", option=11)), kind="TXT"),
    _q(3, _rule(_cond(2, "exists")), kind="TXT"),
    _q(4, kind="TXT"),
]
ALL_RULE = [
    _q(1, options=PICKS, kind="MULT"),
    _q(2, options=YES_NO),
    _q(3, _rule(_cond(2, "=", option=12), _cond(1, "exists"), behavior="all")),
]
CASES = {
    "chain holds": (CHAIN, {"1": "11", "2": "a", "3": "b", "4": "c"}),
    "chain collapses, stale answers dropped": (CHAIN, {"1": "12", "2": "x", "3": "y"}),
    "chain, middle blank": (CHAIN, {"1": "11", "2": "  ", "3": "y"}),
    "all: one condition short": (ALL_RULE, {"2": "12", "3": "11"}),
    "all: both met": (ALL_RULE, {"1": ["21"], "2": "12", "3": "11"}),
    "any with a stale hidden answer": (
        [
            _q(1, options=YES_NO),
            _q(2, _rule(_cond(1, "=", option=11)), kind="TXT"),
            _q(3, _rule(_cond(2, "exists"), _cond(1, "=", option=11)), kind="TXT"),
        ],
        {"1": "12", "2": "stale", "3": "z"},
    ),
    "multi-select equals one pick": (
        [_q(1, options=PICKS, kind="MULT"), _q(2, _rule(_cond(1, "=", option=22)), kind="TXT")],
        {"1": ["21", "22"], "2": "t"},
    ),
    "not equals by text value": (
        [_q(1, options=YES_NO), _q(2, _rule(_cond(1, "!=", value=" YES ")), kind="TXT")],
        {"1": "12", "2": "t"},
    ),
    "equals by option code": (
        [_q(1, options=YES_NO), _q(2, _rule(_cond(1, "=", value="y")), kind="TXT")],
        {"1": "11", "2": "t"},
    ),
    "free-text equals": (
        [_q(1, kind="TXT"), _q(2, _rule(_cond(1, "=", value="Done")), kind="TXT")],
        {"1": " done ", "2": "t"},
    ),
    "not_exists hides once answered": (
        [_q(1, kind="TXT"), _q(2, _rule(_cond(1, "not_exists")), kind="TXT")],
        {"1": "a", "2": "x"},
    ),
    "rule on a later question": (
        [
            _q(1, _rule(_cond(3, "=", option=11)), kind="TXT"),
            _q(2, _rule(_cond(1, "exists")), kind="TXT"),
            _q(3, options=YES_NO),
        ],
        {"1": "a", "2": "b", "3": "12"},
    ),
    "rule names a missing question": (
        [_q(1, _rule(_cond(99, "exists")), kind="TXT"), _q(2, kind="TXT")],
        {"1": "a", "2": "b"},
    ),
    "cycle, both answered": (
        [
            _q(1, _rule(_cond(2, "exists")), kind="TXT"),
            _q(2, _rule(_cond(1, "exists")), kind="TXT"),
        ],
        {"1": "a", "2": "b"},
    ),
    "cycle, one answered": (
        [
            _q(1, _rule(_cond(2, "exists")), kind="TXT"),
            _q(2, _rule(_cond(1, "exists")), kind="TXT"),
        ],
        {"1": "a"},
    ),
    "nothing answered": (CHAIN, {}),
}


def _python(questions, answers):
    kept = visible_answers(questions, answers)
    by_id = {str(q["id"]): q for q in questions}
    return {"kept": kept, "shown": [is_shown(q, kept, by_id) for q in questions]}


def _rule_block() -> str:
    start, end = TEMPLATE.find(START), TEMPLATE.find(END)
    assert 0 <= start < end, "Field Rules markers missing from form.html"
    return TEMPLATE[start:end]


def _javascript(cases):
    script = (
        _rule_block()
        + """
const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
const out = {};
for (const [name, [questions, answers]] of Object.entries(cases)) {
  const byId = {};
  questions.forEach(function (q) { byId[String(q.id)] = q; });
  const kept = visibleAnswers(questions, answers, byId);
  out[name] = { kept: kept, shown: questions.map(function (q) { return isShown(q, kept, byId); }) };
}
process.stdout.write(JSON.stringify(out));
"""
    )
    assert NODE is not None
    result = subprocess.run(
        [NODE, "-e", script], input=json.dumps(cases), capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def test_rule_block_is_pure():
    """The cut-out block must not touch the page, so node can run it as shipped."""
    block = _rule_block()
    assert not re.search(r"\b(document|window|fetch|localStorage|sessionStorage)\b", block)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_javascript_rules_match_python():
    javascript = _javascript(CASES)
    for name, (questions, answers) in CASES.items():
        assert javascript[name] == _python(questions, answers), name


def test_hiding_a_question_keeps_its_input():
    """A hidden question keeps what was typed, so flipping the parent back restores it;
    the answer is only left out when saved (Python drops it again on the server)."""
    apply_rules = TEMPLATE.split("function applyRules() {")[1].split("\n  }")[0]
    assert "block.hidden = " in apply_rules
    assert ".value = " not in apply_rules
    assert ".checked = " not in apply_rules
