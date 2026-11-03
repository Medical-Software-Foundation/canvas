import re
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parent.parent / "conditional_questionnaire" / "templates" / "form.html"
).read_text()


def _function_body(name: str) -> str:
    match = re.search(rf"function {name}\(\) \{{(.*?)\n  \}}", TEMPLATE, re.DOTALL)
    assert match, f"{name} not found in form.html"
    return match.group(1)


def test_failed_save_banner_clears_when_answers_change() -> None:
    """A save error describes the answers as sent; editing them must clear the banner."""
    assert 'list.addEventListener("input", onAnswersChanged)' in TEMPLATE
    assert 'list.addEventListener("change", onAnswersChanged)' in TEMPLATE
    body = _function_body("onAnswersChanged")
    assert "if (saveFailed)" in body
    assert 'show("")' in body
    assert "applyRules()" in body


def test_save_failure_sets_the_flag_and_a_new_form_resets_it() -> None:
    marker = "}).catch(function (error) {\n      saveButton.disabled = false;"
    catch_block = TEMPLATE.split(marker)[1]
    assert catch_block.lstrip().startswith("saveFailed = true;")
    draw = TEMPLATE.split("function drawForm(data) {")[1].split("\n  }")[0]
    assert "saveFailed = false;" in draw
