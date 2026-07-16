"""Tests for consent_capture/questions.py."""

from consent_capture.questions import (
    QUESTION_TYPES,
    evaluate_answers,
    normalize_questions,
)


class TestNormalizeQuestions:
    def test_non_list_returns_empty(self):
        assert normalize_questions(None) == []
        assert normalize_questions("nope") == []

    def test_drops_blank_prompts_and_non_dicts(self):
        out = normalize_questions([{"prompt": "  "}, "x", {"prompt": "Real?"}])
        assert len(out) == 1
        assert out[0]["prompt"] == "Real?"

    def test_defaults_and_coercion(self):
        out = normalize_questions([{"prompt": "Q1"}])
        q = out[0]
        assert q["type"] == "yes_no"       # default type
        assert q["required"] is True        # default required
        assert q["affirm"] is False         # default affirm
        assert q["id"] == "q1"              # assigned id

    def test_unknown_type_falls_back_to_yes_no(self):
        assert normalize_questions([{"prompt": "Q", "type": "slider"}])[0]["type"] == "yes_no"

    def test_text_forces_affirm_false(self):
        out = normalize_questions([{"prompt": "Notes", "type": "text", "affirm": True}])
        assert out[0]["affirm"] is False

    def test_keeps_provided_id_and_string_bools(self):
        out = normalize_questions(
            [{"id": "aff", "prompt": "OK?", "type": "yes_no", "required": "true", "affirm": "1"}]
        )
        assert out[0]["id"] == "aff"
        assert out[0]["required"] is True
        assert out[0]["affirm"] is True

    def test_all_types_valid(self):
        assert set(QUESTION_TYPES) == {"yes_no", "acknowledge", "text"}

    def test_non_bool_non_string_flag_coerced(self):
        # required given as an int (1) exercises the bool(value) fallback path.
        out = normalize_questions([{"prompt": "Q", "required": 1, "affirm": 0}])
        assert out[0]["required"] is True
        assert out[0]["affirm"] is False


AFFIRM_YESNO = {"id": "a", "prompt": "Agree?", "type": "yes_no", "required": True, "affirm": True}
ACK = {"id": "b", "prompt": "Confirm", "type": "acknowledge", "required": True, "affirm": True}
TEXT_REQ = {"id": "c", "prompt": "Notes", "type": "text", "required": True, "affirm": False}


class TestEvaluateAnswers:
    def test_no_questions_ok(self):
        ok, err, resp = evaluate_answers([], {})
        assert ok is True and err == "" and resp == []

    def test_required_missing_blocks(self):
        ok, err, resp = evaluate_answers([AFFIRM_YESNO], {})
        assert ok is False
        assert "Please answer" in err
        assert resp == []

    def test_required_acknowledge_missing_uses_confirm_wording(self):
        ok, err, _ = evaluate_answers([ACK], {})
        assert ok is False and "Please confirm" in err

    def test_affirm_no_blocks_and_records_nothing(self):
        ok, err, resp = evaluate_answers([AFFIRM_YESNO], {"a": "No"})
        assert ok is False
        assert "Consent was not granted" in err
        assert resp == []

    def test_acknowledge_unchecked_blocks(self):
        ok, err, _ = evaluate_answers([ACK], {"b": ""})
        assert ok is False and "Please confirm" in err

    def test_happy_path_builds_responses(self):
        questions = [AFFIRM_YESNO, ACK, TEXT_REQ]
        answers = {"a": "Yes", "b": "yes", "c": "Patient was alert."}
        ok, err, resp = evaluate_answers(questions, answers)
        assert ok is True and err == ""
        assert resp == [
            ("Agree?", "Yes"),
            ("Confirm", "Confirmed"),
            ("Notes", "Patient was alert."),
        ]

    def test_optional_unanswered_is_skipped_in_responses(self):
        q = {"id": "n", "prompt": "Notes", "type": "text", "required": False, "affirm": False}
        ok, err, resp = evaluate_answers([q], {})
        assert ok is True
        assert resp == []

    def test_non_affirm_yes_no_records_no(self):
        q = {"id": "x", "prompt": "Interpreter used?", "type": "yes_no", "required": True, "affirm": False}
        ok, err, resp = evaluate_answers([q], {"x": "No"})
        assert ok is True
        assert resp == [("Interpreter used?", "No")]

    def test_optional_yes_no_unanswered_skipped(self):
        q = {"id": "x", "prompt": "Interpreter used?", "type": "yes_no", "required": False, "affirm": False}
        ok, err, resp = evaluate_answers([q], {})
        assert ok is True
        assert resp == []

    def test_non_dict_question_is_skipped(self):
        ok, err, resp = evaluate_answers(["not-a-dict", TEXT_REQ], {"c": "note"})
        assert ok is True
        assert resp == [("Notes", "note")]
