"""Tests for clinical_pathways.handlers.evaluator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.questionnaire import Interview

from clinical_pathways.handlers import evaluator as evaluator_mod
from clinical_pathways.handlers.evaluator import (
    PathwayEvaluator,
    _collect_responses_for_interview,
    _evaluate_condition,
    _evaluate_rule,
    _find_recommendation,
    _find_step,
    _op_contains,
    _op_eq,
    _op_num,
    _questionnaire_command,
    _recommendation_command,
    _resolve_template,
    _set_overlap,
    _set_superset,
    _severity_label,
)
from clinical_pathways.models import Pathway, PathwayRun


# ---------- Operator helpers ----------


class TestOperatorPrimitives:
    def test_op_eq_normalizes_whitespace_and_case(self) -> None:
        assert _op_eq("  Yes  ", "yes") is True
        assert _op_eq(None, "") is True
        assert _op_eq("no", "yes") is False

    def test_op_contains(self) -> None:
        assert _op_contains("Severe cough", "cough") is True
        assert _op_contains("Severe cough", "fever") is False
        assert _op_contains(None, "x") is False

    @pytest.mark.parametrize(
        "answer,expected,cmp,result",
        [
            ("5", "3", "gt", True),
            ("3", "5", "gt", False),
            ("5", "5", "gte", True),
            ("3", "5", "lte", True),
            ("3", "5", "lt", True),
            ("not-a-number", "3", "gt", False),
            ("3", "5", "garbage_op", False),
        ],
    )
    def test_op_num(self, answer: str, expected: str, cmp: str, result: bool) -> None:
        assert _op_num(answer, expected, cmp) is result

    def test_set_overlap(self) -> None:
        assert _set_overlap(["A", "b"], ["B"]) is True
        assert _set_overlap([], ["x"]) is False

    def test_set_superset(self) -> None:
        assert _set_superset(["A", "B", "C"], ["a", "b"]) is True
        assert _set_superset(["A"], ["a", "b"]) is False


# ---------- _evaluate_condition ----------


class TestEvaluateCondition:
    def test_missing_question_id_is_false(self) -> None:
        assert _evaluate_condition({}, {}) is False

    def test_any_answer_true_when_text_present(self) -> None:
        captured = {"q1": {"text": "yes", "option_ids": []}}
        assert _evaluate_condition(
            {"question_id": "q1", "operator": "any_answer"}, captured
        ) is True

    def test_any_answer_false_when_bucket_missing(self) -> None:
        assert _evaluate_condition(
            {"question_id": "q1", "operator": "any_answer"}, {}
        ) is False

    def test_no_answer_true_when_bucket_missing(self) -> None:
        assert _evaluate_condition(
            {"question_id": "q1", "operator": "no_answer"}, {}
        ) is True

    def test_no_answer_true_when_bucket_blank(self) -> None:
        captured = {"q1": {"text": "", "option_ids": []}}
        assert _evaluate_condition(
            {"question_id": "q1", "operator": "no_answer"}, captured
        ) is True

    def test_eq_text(self) -> None:
        captured = {"q1": {"text": "yes", "option_ids": []}}
        assert (
            _evaluate_condition(
                {"question_id": "q1", "operator": "eq", "value_text": "Yes"},
                captured,
            )
            is True
        )

    def test_eq_option_id(self) -> None:
        captured = {"q1": {"text": "", "option_ids": ["42"]}}
        assert (
            _evaluate_condition(
                {"question_id": "q1", "operator": "eq", "value_option_id": "42"},
                captured,
            )
            is True
        )

    def test_neq_text(self) -> None:
        captured = {"q1": {"text": "no", "option_ids": []}}
        assert (
            _evaluate_condition(
                {"question_id": "q1", "operator": "neq", "value_text": "yes"},
                captured,
            )
            is True
        )

    def test_neq_option_id_when_not_selected(self) -> None:
        captured = {"q1": {"text": "", "option_ids": ["1"]}}
        assert (
            _evaluate_condition(
                {"question_id": "q1", "operator": "neq", "value_option_id": "99"},
                captured,
            )
            is True
        )

    def test_contains(self) -> None:
        captured = {"q1": {"text": "severe cough", "option_ids": []}}
        assert (
            _evaluate_condition(
                {"question_id": "q1", "operator": "contains", "value_text": "cough"},
                captured,
            )
            is True
        )

    def test_numeric_operators(self) -> None:
        captured = {"q1": {"text": "10", "option_ids": []}}
        assert (
            _evaluate_condition(
                {"question_id": "q1", "operator": "gt", "value_number": "5"},
                captured,
            )
            is True
        )

    def test_contains_any(self) -> None:
        captured = {"q1": {"option_ids": ["A", "B"]}}
        assert (
            _evaluate_condition(
                {
                    "question_id": "q1",
                    "operator": "contains_any",
                    "value_option_ids": ["B", "C"],
                },
                captured,
            )
            is True
        )

    def test_contains_all(self) -> None:
        captured = {"q1": {"option_ids": ["A", "B", "C"]}}
        assert (
            _evaluate_condition(
                {
                    "question_id": "q1",
                    "operator": "contains_all",
                    "value_option_ids": ["A", "B"],
                },
                captured,
            )
            is True
        )

    def test_contains_none(self) -> None:
        captured = {"q1": {"option_ids": ["A"]}}
        assert (
            _evaluate_condition(
                {
                    "question_id": "q1",
                    "operator": "contains_none",
                    "value_option_ids": ["B"],
                },
                captured,
            )
            is True
        )

    def test_contains_falls_back_to_singleton_value_option_id(self) -> None:
        captured = {"q1": {"option_ids": ["B"]}}
        assert (
            _evaluate_condition(
                {
                    "question_id": "q1",
                    "operator": "contains_any",
                    "value_option_id": "B",
                },
                captured,
            )
            is True
        )

    def test_unknown_operator_returns_false(self) -> None:
        captured = {"q1": {"text": "y", "option_ids": []}}
        assert (
            _evaluate_condition(
                {"question_id": "q1", "operator": "xyzzy", "value_text": "y"},
                captured,
            )
            is False
        )


# ---------- _evaluate_rule ----------


def _cond(qid: str, text: str, connector: str | None = None) -> dict[str, Any]:
    c: dict[str, Any] = {"question_id": qid, "operator": "eq", "value_text": text}
    if connector:
        c["connector"] = connector
    return c


class TestEvaluateRule:
    def test_empty_conditions_is_false(self) -> None:
        assert _evaluate_rule({"conditions": []}, {}) is False

    def test_legacy_combinator_all(self) -> None:
        captured = {"q1": {"text": "y"}, "q2": {"text": "y"}}
        rule = {
            "combinator": "all",
            "conditions": [_cond("q1", "y"), _cond("q2", "y")],
        }
        assert _evaluate_rule(rule, captured) is True

    def test_legacy_combinator_all_negative(self) -> None:
        captured = {"q1": {"text": "y"}, "q2": {"text": "n"}}
        rule = {
            "combinator": "all",
            "conditions": [_cond("q1", "y"), _cond("q2", "y")],
        }
        assert _evaluate_rule(rule, captured) is False

    def test_legacy_combinator_any(self) -> None:
        captured = {"q1": {"text": "n"}, "q2": {"text": "y"}}
        rule = {
            "combinator": "any",
            "conditions": [_cond("q1", "y"), _cond("q2", "y")],
        }
        assert _evaluate_rule(rule, captured) is True

    def test_per_condition_or_takes_precedence_over_legacy_combinator(self) -> None:
        # When per-condition connectors exist, `combinator` is ignored.
        captured = {"q1": {"text": "y"}, "q2": {"text": "n"}}
        rule = {
            "combinator": "all",
            "conditions": [_cond("q1", "y"), _cond("q2", "y", connector="or")],
        }
        # Groups: [q1=y] OR [q2=y]; first group is satisfied, so True.
        assert _evaluate_rule(rule, captured) is True

    def test_and_or_grouping(self) -> None:
        # A AND B OR C AND D → (A AND B) OR (C AND D)
        captured = {
            "q1": {"text": "n"},
            "q2": {"text": "n"},
            "q3": {"text": "y"},
            "q4": {"text": "y"},
        }
        rule = {
            "conditions": [
                _cond("q1", "y"),
                _cond("q2", "y", connector="and"),
                _cond("q3", "y", connector="or"),
                _cond("q4", "y", connector="and"),
            ]
        }
        assert _evaluate_rule(rule, captured) is True


# ---------- _find_step / _find_recommendation / _resolve_template / _severity_label ----------


class TestFindHelpers:
    def test_find_step_returns_match(self) -> None:
        definition = {"steps": [{"step_id": "s_a"}, {"step_id": "s_b"}]}
        assert _find_step(definition, "s_b") == {"step_id": "s_b"}

    def test_find_step_returns_none_for_missing(self) -> None:
        assert _find_step({"steps": [{"step_id": "s_a"}]}, "s_b") is None

    def test_find_step_with_empty_step_id(self) -> None:
        assert _find_step({"steps": []}, "") is None

    def test_find_step_ignores_non_dict_entries(self) -> None:
        assert _find_step({"steps": ["junk", {"step_id": "s_a"}]}, "s_a") == {
            "step_id": "s_a"
        }

    def test_find_recommendation(self) -> None:
        definition = {
            "recommendations": [
                {"recommendation_id": "rec1", "name": "X"},
                {"recommendation_id": "rec2"},
            ]
        }
        assert _find_recommendation(definition, "rec1")["name"] == "X"
        assert _find_recommendation(definition, "nope") is None

    def test_find_recommendation_empty_id(self) -> None:
        assert _find_recommendation({"recommendations": []}, "") is None


class TestResolveTemplate:
    def test_resolve_text_value(self) -> None:
        captured = {"q1": {"text": "yes"}}
        assert _resolve_template("Answer: {{q1}}", captured) == "Answer: yes"

    def test_resolve_missing_question_yields_empty(self) -> None:
        assert _resolve_template("{{q1}}", {}) == ""

    def test_resolve_falls_back_to_values_list(self) -> None:
        captured = {"q1": {"text": "", "values": ["A", "B"]}}
        assert _resolve_template("{{q1}}", captured) == "A, B"

    def test_resolve_non_string_input(self) -> None:
        assert _resolve_template(123, {}) == "123"
        assert _resolve_template(None, {}) == ""


class TestSeverityLabel:
    SPEC = {
        "fields": [
            {
                "key": "severity",
                "options": [
                    {"value": "minor", "label": "Minor"},
                    {"value": "severe", "label": "Severe"},
                ],
            },
            {"key": "title"},
        ]
    }

    def test_returns_label_when_value_matches(self) -> None:
        assert _severity_label(self.SPEC, "severe") == "Severe"

    def test_falls_back_to_title_case(self) -> None:
        assert _severity_label(self.SPEC, "critical") == "Critical"

    def test_blank_value_returns_empty(self) -> None:
        assert _severity_label(self.SPEC, "") == ""

    def test_no_severity_field_returns_title_case(self) -> None:
        assert _severity_label({"fields": []}, "minor") == "Minor"


# ---------- _collect_responses_for_interview ----------


def _resp(
    question_id: int | None = 1,
    question_uuid: str | None = "q-uuid-1",
    option_id: int | None = None,
    option_value: str | None = None,
) -> Any:
    r = MagicMock()
    r.question_id = question_id
    if question_uuid is None:
        r.question = None
    else:
        r.question = MagicMock()
        r.question.id = question_uuid
    r.response_option_id = option_id
    r.response_option_value = option_value
    return r


class TestCollectResponsesForInterview:
    def test_collects_text_responses(self) -> None:
        interview = MagicMock()
        interview.interview_responses.all.return_value = [
            _resp(option_value="yes"),
        ]
        result = _collect_responses_for_interview(interview)
        assert result == {
            "q-uuid-1": {"text": "yes", "option_ids": [], "values": ["yes"]}
        }

    def test_collects_option_ids(self) -> None:
        interview = MagicMock()
        interview.interview_responses.all.return_value = [
            _resp(option_id=99, option_value=None),
        ]
        result = _collect_responses_for_interview(interview)
        assert result["q-uuid-1"]["option_ids"] == ["99"]

    def test_skips_responses_without_question_id(self) -> None:
        interview = MagicMock()
        interview.interview_responses.all.return_value = [_resp(question_id=None)]
        assert _collect_responses_for_interview(interview) == {}

    def test_skips_when_question_uuid_unavailable(self) -> None:
        interview = MagicMock()
        interview.interview_responses.all.return_value = [_resp(question_uuid=None)]
        assert _collect_responses_for_interview(interview) == {}

    def test_handles_question_resolution_failure(self) -> None:
        r = MagicMock()
        r.question_id = 1
        # Accessing .question raises (e.g. RelatedObjectDoesNotExist surrogate).
        type(r).question = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        r.response_option_id = None
        r.response_option_value = None
        interview = MagicMock()
        interview.interview_responses.all.return_value = [r]
        assert _collect_responses_for_interview(interview) == {}

    def test_merges_multi_select_responses(self) -> None:
        interview = MagicMock()
        interview.interview_responses.all.return_value = [
            _resp(option_id=1, option_value="A"),
            _resp(option_id=2, option_value="B"),
        ]
        result = _collect_responses_for_interview(interview)
        assert sorted(result["q-uuid-1"]["option_ids"]) == ["1", "2"]
        assert sorted(result["q-uuid-1"]["values"]) == ["A", "B"]
        # First text wins.
        assert result["q-uuid-1"]["text"] == "A"


# ---------- Command builders ----------


class TestQuestionnaireCommandBuilder:
    def test_builds_with_note_uuid_and_command_uuid(self) -> None:
        cmd = _questionnaire_command("qn-123", "note-uuid")
        assert cmd.note_uuid == "note-uuid"
        assert cmd.questionnaire_id == "qn-123"
        assert cmd.command_uuid  # non-empty


class TestRecommendationCommand:
    def _spec_aware_recommendation(self) -> dict[str, Any]:
        return {
            "recommendation_id": "rec1",
            "name": "Mild",
            "command_key": "pathway_classification",
            "params": {
                "title": "T",
                "severity": "minor",
                "body": "B - {{q1}}",
            },
        }

    def test_returns_none_when_command_key_unknown(self) -> None:
        rec = {"command_key": "unknown"}
        pathway = MagicMock(title="X")
        assert _recommendation_command(rec, pathway, "note-1", {}) is None

    def test_builds_custom_command_with_resolved_params(self) -> None:
        rec = self._spec_aware_recommendation()
        pathway = MagicMock(title="Asthma")
        captured = {"q1": {"text": "yes"}}

        # Capture the template context to verify resolved values.
        captured_contexts: list[dict[str, Any]] = []

        def _spy_render(template_name: str, context: dict[str, Any] | None = None) -> str:
            captured_contexts.append(dict(context or {}))
            return "<rendered>"

        with patch.object(evaluator_mod, "render_to_string", _spy_render):
            cmd = _recommendation_command(rec, pathway, "note-1", captured)

        assert cmd is not None
        assert cmd.schema_key == "pathwayClassification"
        assert cmd.note_uuid == "note-1"
        # The template received the resolved body with q1's captured response.
        assert captured_contexts[0]["body"] == "B - yes"
        assert captured_contexts[0]["pathway_title"] == "Asthma"
        assert captured_contexts[0]["severity_label"] == "Minor"


# ---------- PathwayEvaluator.compute() ----------


def _make_evaluator(
    *,
    interview: Any = None,
    note: Any = None,
    runs: list[Any] | None = None,
) -> PathwayEvaluator:
    handler = PathwayEvaluator()
    handler.event = MagicMock()
    handler.event.target = MagicMock()
    handler.event.target.id = "intv-1"
    return handler


def _committed_interview(
    *,
    note_id: int = 5,
    questionnaire_ids: list[str] | None = None,
    responses: list[Any] | None = None,
    modified: datetime | None = None,
) -> Any:
    interview = MagicMock()
    interview.committer_id = 42
    interview.entered_in_error_id = None
    interview.note_id = note_id
    qns = []
    for qid in questionnaire_ids or []:
        q = MagicMock()
        q.id = qid
        qns.append(q)
    interview.questionnaires.all.return_value = qns
    interview.interview_responses.all.return_value = responses or []
    interview.modified = modified
    return interview


def _note(note_uuid: str = "note-uuid-1") -> Any:
    note = MagicMock()
    note.id = note_uuid
    return note


class TestComputeEarlyExits:
    def test_returns_empty_when_no_event_target(self) -> None:
        handler = PathwayEvaluator()
        handler.event = None
        assert handler.compute() == []

    def test_returns_empty_when_interview_missing(self) -> None:
        handler = _make_evaluator()
        with patch.object(Interview, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = None
            assert handler.compute() == []

    def test_returns_empty_when_interview_not_committed(self) -> None:
        handler = _make_evaluator()
        interview = MagicMock(committer_id=None, entered_in_error_id=None)
        with patch.object(Interview, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = interview
            assert handler.compute() == []

    def test_returns_empty_when_interview_entered_in_error(self) -> None:
        handler = _make_evaluator()
        interview = MagicMock(committer_id=1, entered_in_error_id=2)
        with patch.object(Interview, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = interview
            assert handler.compute() == []

    def test_returns_empty_when_interview_has_no_note_id(self) -> None:
        handler = _make_evaluator()
        interview = _committed_interview(note_id=None)
        with patch.object(Interview, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = interview
            assert handler.compute() == []

    def test_returns_empty_when_note_not_found(self) -> None:
        handler = _make_evaluator()
        interview = _committed_interview()
        with (
            patch.object(Interview, "objects") as mock_intv,
            patch.object(Note, "objects") as mock_note,
        ):
            mock_intv.filter.return_value.first.return_value = interview
            mock_note.filter.return_value.first.return_value = None
            assert handler.compute() == []

    def test_returns_empty_when_no_active_runs(self) -> None:
        handler = _make_evaluator()
        interview = _committed_interview()
        runs_qs = MagicMock()
        runs_qs.exists.return_value = False
        with (
            patch.object(Interview, "objects") as mock_intv,
            patch.object(Note, "objects") as mock_note,
            patch.object(PathwayRun, "objects") as mock_runs,
        ):
            mock_intv.filter.return_value.first.return_value = interview
            mock_note.filter.return_value.first.return_value = _note()
            mock_runs.filter.return_value = runs_qs
            assert handler.compute() == []

    def test_event_target_with_no_id_returns_empty(self) -> None:
        handler = PathwayEvaluator()
        handler.event = MagicMock()
        handler.event.target = MagicMock()
        handler.event.target.id = None
        assert handler.compute() == []


# ---------- Integration scenarios driving _advance() ----------


def _published_pathway(definition: dict, dbid: int = 11, title: str = "P") -> Any:
    pw = MagicMock(spec_set=["dbid", "title", "definition"])
    pw.dbid = dbid
    pw.title = title
    pw.definition = definition
    return pw


def _active_run(
    *,
    dbid: int = 1,
    pathway_id: int = 11,
    current_step_id: str = "s_a",
    inserted: list[str] | None = None,
    committed: list[str] | None = None,
    captured: dict | None = None,
    last_token: str = "",
) -> MagicMock:
    run = MagicMock()
    run.dbid = dbid
    run.pathway_id = pathway_id
    run.current_step_id = current_step_id
    run.inserted_questionnaires = list(inserted or [])
    run.committed_questionnaires = list(committed or [])
    run.captured_responses = dict(captured or {})
    run.last_processed_event_token = last_token
    run.status = "active"
    return run


def _wire_run_token_claim(mock_runs: MagicMock, updated_rows: int = 1) -> None:
    """Ensure the second `PathwayRun.objects.filter(...).update(...)` call
    returns `updated_rows` so the worker either wins (1) or loses (0)."""
    update_qs = MagicMock()
    update_qs.update.return_value = updated_rows
    # The first .filter call returns runs (an iterable); the second returns
    # a queryset whose `.update()` produces the row-claim result. We give
    # both calls the same mock and override behavior per-call.

    def filter_side_effect(*args: Any, **kwargs: Any) -> Any:
        if "dbid" in kwargs and "last_processed_event_token" in kwargs:
            return update_qs
        # First call: filter(note_uuid=..., status="active")
        return mock_runs._runs_qs

    mock_runs.filter.side_effect = filter_side_effect


def _setup_compute_mocks(
    *,
    interview: Any,
    note: Any,
    runs: list[Any],
    pathway: Any,
    pathway_lookup_returns: Any | None = None,
    updated_rows: int = 1,
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Common patching scaffolding for compute() integration tests."""
    mock_intv = patch.object(Interview, "objects").start()
    mock_note = patch.object(Note, "objects").start()
    mock_run_objects = patch.object(PathwayRun, "objects").start()
    mock_pw_objects = patch.object(Pathway, "objects").start()

    mock_intv.filter.return_value.first.return_value = interview
    mock_note.filter.return_value.first.return_value = note

    runs_qs = MagicMock()
    runs_qs.exists.return_value = bool(runs)
    runs_qs.__iter__ = lambda self: iter(runs)
    mock_run_objects._runs_qs = runs_qs
    _wire_run_token_claim(mock_run_objects, updated_rows=updated_rows)

    pathway_qs = MagicMock()
    pathway_qs.first.return_value = (
        pathway_lookup_returns if pathway_lookup_returns is not None else pathway
    )
    mock_pw_objects.filter.return_value = pathway_qs

    return mock_intv, mock_note, mock_run_objects, mock_pw_objects


def _teardown() -> None:
    patch.stopall()


class TestComputeIntegration:
    def teardown_method(self) -> None:
        _teardown()

    def test_skips_run_when_pathway_lookup_fails(self) -> None:
        handler = _make_evaluator()
        run = _active_run()
        _setup_compute_mocks(
            interview=_committed_interview(),
            note=_note(),
            runs=[run],
            pathway=None,
            pathway_lookup_returns=None,
        )
        effects = handler.compute()
        assert effects == []
        # Since pathway lookup failed, run should NOT have been saved.
        run.save.assert_not_called()

    def test_skips_run_with_pre_v3_definition(self) -> None:
        handler = _make_evaluator()
        run = _active_run()
        pathway = _published_pathway({"version": 2}, dbid=11)
        _setup_compute_mocks(
            interview=_committed_interview(),
            note=_note(),
            runs=[run],
            pathway=pathway,
        )
        effects = handler.compute()
        assert effects == []

    def test_skips_run_when_event_already_processed(self) -> None:
        handler = _make_evaluator()
        # Run's last token equals the event_token we'll compute for an
        # interview with no `modified` timestamp ("intv-1").
        run = _active_run(last_token="intv-1")
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": None,
                }
            ],
            "recommendations": [],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=_committed_interview(),
            note=_note(),
            runs=[run],
            pathway=pathway,
        )
        effects = handler.compute()
        assert effects == []
        run.save.assert_not_called()

    def test_skips_run_when_token_claim_lost(self) -> None:
        handler = _make_evaluator()
        run = _active_run(last_token="")
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": None,
                }
            ],
            "recommendations": [],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=_committed_interview(),
            note=_note(),
            runs=[run],
            pathway=pathway,
            updated_rows=0,
        )
        effects = handler.compute()
        assert effects == []
        run.save.assert_not_called()

    def test_inserts_first_questionnaire_when_not_yet_in_note(
        self, stub_effect_type: type
    ) -> None:
        handler = _make_evaluator()
        run = _active_run(inserted=[], committed=[])
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn-A",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": None,
                }
            ],
            "recommendations": [],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=_committed_interview(),
            note=_note(),
            runs=[run],
            pathway=pathway,
        )
        effects = handler.compute()
        assert len(effects) == 1
        assert isinstance(effects[0], stub_effect_type)
        assert effects[0].tag == "BatchOriginateCommandEffect"
        # The run was saved with the new inserted list.
        assert run.inserted_questionnaires == ["qn-A"]
        run.save.assert_called_once_with()

    def test_skips_insert_when_questionnaire_already_in_note(self) -> None:
        handler = _make_evaluator()
        # First step's questionnaire is already inserted; no commit yet.
        run = _active_run(inserted=["qn-A"], committed=[])
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn-A",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": None,
                }
            ],
            "recommendations": [],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=_committed_interview(),
            note=_note(),
            runs=[run],
            pathway=pathway,
        )
        effects = handler.compute()
        assert effects == []

    def test_routes_through_step_to_recommendation_originates_custom_command(
        self, stub_effect_type: type
    ) -> None:
        handler = _make_evaluator()
        # The just-committed interview supplies an answer to q1 = "yes",
        # which matches the rule that routes to recommendation rec1.
        intv_qid = "qn-A"
        responses = [_resp(option_value="yes", question_uuid="q1")]
        interview = _committed_interview(
            questionnaire_ids=[intv_qid], responses=responses
        )
        run = _active_run(
            inserted=["qn-A"],
            committed=["qn-A"],
            captured={},
        )
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn-A",
                    "question_id": "q1",
                    "rules": [
                        {
                            "rule_id": "r1",
                            "conditions": [
                                {
                                    "question_id": "q1",
                                    "operator": "eq",
                                    "value_text": "yes",
                                }
                            ],
                            "then": {
                                "type": "recommendation",
                                "target_id": "rec1",
                            },
                        }
                    ],
                    "otherwise": None,
                }
            ],
            "recommendations": [
                {
                    "recommendation_id": "rec1",
                    "name": "Severe",
                    "command_key": "pathway_classification",
                    "params": {"title": "T", "body": "B"},
                }
            ],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=interview,
            note=_note(),
            runs=[run],
            pathway=pathway,
        )
        effects = handler.compute()
        assert len(effects) == 1
        assert isinstance(effects[0], stub_effect_type)
        assert effects[0].tag == "CustomCommand.originate"
        assert run.status == "completed"

    def test_routes_via_otherwise_when_no_rule_matches(
        self, stub_effect_type: type
    ) -> None:
        handler = _make_evaluator()
        # No matching rule → fall through to `otherwise` → second step.
        interview = _committed_interview(questionnaire_ids=["qn-A"])
        run = _active_run(
            inserted=["qn-A"],
            committed=["qn-A"],
        )
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn-A",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": {"type": "step", "target_id": "s_b"},
                },
                {
                    "step_id": "s_b",
                    "questionnaire_id": "qn-B",
                    "question_id": "q2",
                    "rules": [],
                    "otherwise": None,
                },
            ],
            "recommendations": [],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=interview,
            note=_note(),
            runs=[run],
            pathway=pathway,
        )
        effects = handler.compute()
        # Step B's questionnaire was not yet inserted → expect one
        # BatchOriginateCommandEffect for qn-B.
        assert len(effects) == 1
        assert effects[0].tag == "BatchOriginateCommandEffect"
        assert run.current_step_id == "s_b"

    def test_completes_when_step_routes_to_missing_recommendation(self) -> None:
        handler = _make_evaluator()
        interview = _committed_interview(questionnaire_ids=["qn-A"])
        run = _active_run(inserted=["qn-A"], committed=["qn-A"])
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn-A",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": {"type": "recommendation", "target_id": "rec_missing"},
                }
            ],
            "recommendations": [],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=interview, note=_note(), runs=[run], pathway=pathway,
        )
        effects = handler.compute()
        assert effects == []
        assert run.status == "completed"

    def test_completes_when_step_routes_to_missing_step(self) -> None:
        handler = _make_evaluator()
        interview = _committed_interview(questionnaire_ids=["qn-A"])
        run = _active_run(inserted=["qn-A"], committed=["qn-A"])
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn-A",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": {"type": "step", "target_id": "s_missing"},
                }
            ],
            "recommendations": [],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=interview, note=_note(), runs=[run], pathway=pathway,
        )
        effects = handler.compute()
        assert effects == []
        assert run.status == "completed"

    def test_completes_when_target_type_unknown(self) -> None:
        handler = _make_evaluator()
        interview = _committed_interview(questionnaire_ids=["qn-A"])
        run = _active_run(inserted=["qn-A"], committed=["qn-A"])
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn-A",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": {"type": "bogus", "target_id": "x"},
                }
            ],
            "recommendations": [],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=interview, note=_note(), runs=[run], pathway=pathway,
        )
        effects = handler.compute()
        assert effects == []
        assert run.status == "completed"

    def test_completes_when_step_has_no_target_and_no_rules(self) -> None:
        handler = _make_evaluator()
        interview = _committed_interview(questionnaire_ids=["qn-A"])
        run = _active_run(inserted=["qn-A"], committed=["qn-A"])
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn-A",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": None,
                }
            ],
            "recommendations": [],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=interview, note=_note(), runs=[run], pathway=pathway,
        )
        effects = handler.compute()
        assert effects == []
        assert run.status == "completed"

    def test_malformed_step_terminates_run(self) -> None:
        handler = _make_evaluator()
        interview = _committed_interview(questionnaire_ids=["qn-A"])
        run = _active_run(inserted=[], committed=[])
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                # missing questionnaire_id / question_id
                {"step_id": "s_a", "rules": [], "otherwise": None},
            ],
            "recommendations": [],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=interview, note=_note(), runs=[run], pathway=pathway,
        )
        effects = handler.compute()
        assert effects == []
        assert run.status == "completed"

    def test_missing_step_in_definition_terminates(self) -> None:
        handler = _make_evaluator()
        interview = _committed_interview(questionnaire_ids=["qn-A"])
        run = _active_run(current_step_id="s_nonexistent")
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn-A",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": None,
                }
            ],
            "recommendations": [],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=interview, note=_note(), runs=[run], pathway=pathway,
        )
        effects = handler.compute()
        assert effects == []
        assert run.status == "completed"

    def test_recommendation_with_unknown_command_key_terminates(self) -> None:
        handler = _make_evaluator()
        interview = _committed_interview(questionnaire_ids=["qn-A"])
        run = _active_run(inserted=["qn-A"], committed=["qn-A"])
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn-A",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": {"type": "recommendation", "target_id": "rec1"},
                }
            ],
            "recommendations": [
                {
                    "recommendation_id": "rec1",
                    "name": "X",
                    "command_key": "unknown_cmd",
                    "params": {},
                }
            ],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=interview, note=_note(), runs=[run], pathway=pathway,
        )
        effects = handler.compute()
        assert effects == []
        assert run.status == "completed"

    def test_interview_modified_appended_to_event_token(self) -> None:
        handler = _make_evaluator()
        interview = _committed_interview(
            modified=datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
        )
        run = _active_run(last_token="")
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn-A",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": None,
                }
            ],
            "recommendations": [],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=interview, note=_note(), runs=[run], pathway=pathway,
        )
        handler.compute()
        # Token gets composed from interview_id + modified.isoformat()
        assert "2026-05-22T12:00:00+00:00" in run.last_processed_event_token

    def test_interview_modified_isoformat_exception_swallowed(self) -> None:
        handler = _make_evaluator()
        interview = _committed_interview()
        # Force isoformat to raise; the evaluator swallows it.
        interview.modified = MagicMock()
        interview.modified.isoformat.side_effect = RuntimeError("boom")
        run = _active_run(last_token="")
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn-A",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": None,
                }
            ],
            "recommendations": [],
        }
        pathway = _published_pathway(definition)
        _setup_compute_mocks(
            interview=interview, note=_note(), runs=[run], pathway=pathway,
        )
        # Should not raise.
        handler.compute()
        # The fallback token is just the interview id.
        assert run.last_processed_event_token == "intv-1"


class TestAdvanceLoopSafety:
    """Drive the 256-iteration safety guard directly via the private _advance()."""

    def teardown_method(self) -> None:
        _teardown()

    def test_loop_guard_terminates_pathological_definition(self) -> None:
        handler = PathwayEvaluator()
        run = _active_run()
        # Self-referential step that always routes back to itself via otherwise.
        definition = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn-A",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": {"type": "step", "target_id": "s_a"},
                }
            ],
            "recommendations": [],
        }
        effects = handler._advance(
            run=run,
            pathway=_published_pathway(definition),
            definition=definition,
            start_step_id="s_a",
            merged={"q1": {"text": "y"}},
            committed_this_event_ids={"qn-A"},
            committed_ever={"qn-A"},
            inserted=["qn-A"],
            note_uuid="note-uuid",
        )
        assert effects == []
        assert run.status == "completed"

    def test_advance_terminates_when_start_step_id_is_blank(self) -> None:
        handler = PathwayEvaluator()
        run = _active_run()
        effects = handler._advance(
            run=run,
            pathway=MagicMock(),
            definition={"version": 3, "steps": [], "recommendations": []},
            start_step_id="",
            merged={},
            committed_this_event_ids=set(),
            committed_ever=set(),
            inserted=[],
            note_uuid="n",
        )
        assert effects == []
        assert run.status == "completed"
