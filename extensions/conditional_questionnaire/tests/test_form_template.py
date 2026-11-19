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


def test_draft_is_kept_per_note_and_questionnaire_in_session_storage() -> None:
    """Unsaved answers survive closing the pane, only for this tab, and keep the UUID."""
    assert "localStorage" not in TEMPLATE
    key = TEMPLATE.split("function draftKey() {")[1].split("\n  }")[0]
    assert "NOTE_ID" in key and "current.id" in key
    store = _function_body("storeDraft")
    assert "sessionStorage.setItem" in store
    assert "uuid: commandUuid" in store and "answers: answers" in store
    # An untouched form leaves no draft, and an empty draft is never "restored".
    assert store.index("if (!draftHasAnswers(answers))") < store.index("setItem")
    assert "removeItem(key)" in store
    assert "!draftHasAnswers(saved.answers)" in _function_body("restoreDraft")
    assert "queueDraft();" in _function_body("onAnswersChanged")
    assert 'document.visibilityState === "hidden"' in TEMPLATE


def test_draft_restores_before_rules_run_and_clears_after_save() -> None:
    restore = _function_body("restoreDraft")
    assert "commandUuid = saved.uuid" in restore
    draw = TEMPLATE.split("function drawForm(data) {")[1].split("\n  }")[0]
    assert draw.index("restoreDraft()") < draw.index("applyRules()")
    saved = TEMPLATE.split("}).then(function () {")[-1]
    assert saved.lstrip().startswith("clearDraft(savingKey);")
    submit = TEMPLATE.split('form.addEventListener("submit"')[1]
    assert submit.index("var savingKey = draftKey();") < submit.index("fetch(")
    assert (
        "if (!key) { return; }" in TEMPLATE.split("function clearDraft(key) {")[1].split("\n  }")[0]
    )
    picked = TEMPLATE.split('picker.addEventListener("change", function () {')[1]
    assert picked.index("storeDraft();") < picked.index("current = null;")


def test_no_function_name_is_declared_twice() -> None:
    """One inline script: a second declaration silently replaces the first (hoisting)."""
    names = re.findall(r"\bfunction (\w+)\s*\(", TEMPLATE)
    assert len(names) == len(set(names)), sorted({n for n in names if names.count(n) > 1})
