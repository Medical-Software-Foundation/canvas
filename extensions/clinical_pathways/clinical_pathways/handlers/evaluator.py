"""Pathway runtime evaluator.

Subscribes to `INTERVIEW_UPDATED` and advances any active `PathwayRun` for the
note the interview belongs to. When the run's current questionnaire is
committed, evaluates the active node's branches against the captured
responses, and emits the next questionnaire — or the terminal CustomCommand —
via `BatchOriginateCommandEffect`.

On-commit semantics: events fire while a questionnaire is being filled in,
not just on commit. We gate strictly on `interview.committer_id` being set,
which is how Canvas marks a finalized interview.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from canvas_sdk.commands import QuestionnaireCommand
from canvas_sdk.commands.commands.custom_command import CustomCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.batch_originate import BatchOriginateCommandEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.questionnaire import Interview
from logger import log

from clinical_pathways.models import Pathway, PathwayRun
from clinical_pathways.terminal_commands import TERMINAL_COMMANDS


# Operator implementations. Operator key matches what the builder emits.
def _op_eq(answer: Any, expected: Any) -> bool:
    return str(answer or "").strip().lower() == str(expected or "").strip().lower()


def _op_neq(answer: Any, expected: Any) -> bool:
    return not _op_eq(answer, expected)


def _op_contains(answer: Any, expected: Any) -> bool:
    return str(expected or "").strip().lower() in str(answer or "").strip().lower()


def _op_num(answer: Any, expected: Any, cmp: str) -> bool:
    try:
        a = float(answer)
        e = float(expected)
    except (TypeError, ValueError):
        return False
    if cmp == "lt":
        return a < e
    if cmp == "lte":
        return a <= e
    if cmp == "gt":
        return a > e
    if cmp == "gte":
        return a >= e
    return False


def _op_any_answer(answer: Any) -> bool:
    return str(answer or "").strip() != ""


def _op_no_answer(answer: Any) -> bool:
    return not _op_any_answer(answer)


def _op_contains_any(answer_list: list[str], expected_list: list[str]) -> bool:
    a = {str(x).strip().lower() for x in answer_list or []}
    e = {str(x).strip().lower() for x in expected_list or []}
    return bool(a & e)


def _op_contains_all(answer_list: list[str], expected_list: list[str]) -> bool:
    a = {str(x).strip().lower() for x in answer_list or []}
    e = {str(x).strip().lower() for x in expected_list or []}
    return e.issubset(a)


def _op_contains_none(answer_list: list[str], expected_list: list[str]) -> bool:
    return not _op_contains_any(answer_list, expected_list)


def _collect_responses_for_interview(interview: Interview) -> dict[str, dict[str, Any]]:
    """Return {question_id_str: {"text": str, "option_ids": [str], "values": [str]}}."""
    responses: dict[str, dict[str, Any]] = {}
    for r in interview.interview_responses.all():
        question_id = str(r.question_id) if r.question_id else None
        if not question_id:
            continue
        bucket = responses.setdefault(
            question_id,
            {"text": "", "option_ids": [], "values": []},
        )
        if r.response_option_id:
            bucket["option_ids"].append(str(r.response_option_id))
        if r.response_option_value:
            bucket["values"].append(r.response_option_value)
            if not bucket["text"]:
                bucket["text"] = r.response_option_value
    return responses


def _evaluate_comparison(comp: dict[str, Any], captured: dict[str, dict[str, Any]]) -> bool:
    qid = str(comp.get("question_id") or "")
    if not qid:
        return False
    op = comp.get("operator", "eq")
    bucket = captured.get(qid)
    if op == "any_answer":
        return bucket is not None and (bool(bucket.get("text")) or bool(bucket.get("option_ids")))
    if op == "no_answer":
        return bucket is None or (not bucket.get("text") and not bucket.get("option_ids"))
    if bucket is None:
        return False

    if op in ("contains_any", "contains_all", "contains_none"):
        expected = comp.get("value_option_ids") or []
        if not expected and comp.get("value_option_id"):
            expected = [comp["value_option_id"]]
        actuals = bucket.get("option_ids", [])
        if op == "contains_any":
            return _op_contains_any(actuals, expected)
        if op == "contains_all":
            return _op_contains_all(actuals, expected)
        return _op_contains_none(actuals, expected)

    answer_text = bucket.get("text", "")
    if op == "eq":
        value_option_id = comp.get("value_option_id")
        if value_option_id:
            return value_option_id in bucket.get("option_ids", [])
        return _op_eq(answer_text, comp.get("value_text"))
    if op == "neq":
        value_option_id = comp.get("value_option_id")
        if value_option_id:
            return value_option_id not in bucket.get("option_ids", [])
        return _op_neq(answer_text, comp.get("value_text"))
    if op == "contains":
        return _op_contains(answer_text, comp.get("value_text"))
    if op in ("lt", "lte", "gt", "gte"):
        return _op_num(answer_text, comp.get("value_number"), op)
    return False


def _evaluate_condition(node: dict[str, Any], captured: dict[str, dict[str, Any]]) -> bool:
    if not isinstance(node, dict):
        return False
    if node.get("kind") == "comparison":
        return _evaluate_comparison(node, captured)
    if node.get("kind") == "group":
        combinator = node.get("combinator", "all")
        children = node.get("children", []) or []
        if not children:
            return False
        if combinator == "all":
            return all(_evaluate_condition(c, captured) for c in children)
        if combinator == "any":
            return any(_evaluate_condition(c, captured) for c in children)
        if combinator == "none":
            return not any(_evaluate_condition(c, captured) for c in children)
    return False


def _find_node(root: dict[str, Any] | None, node_id: str) -> dict[str, Any] | None:
    if not root or not node_id:
        return None
    if root.get("node_id") == node_id:
        return root
    if root.get("type") == "questionnaire":
        for b in root.get("branches", []) or []:
            found = _find_node(b.get("then"), node_id)
            if found:
                return found
    return None


_TEMPLATE_REF = re.compile(r"\{\{\s*([^}|]+?)\s*\}\}")


def _resolve_template(value: Any, captured: dict[str, dict[str, Any]]) -> str:
    if not isinstance(value, str):
        return "" if value is None else str(value)

    def _replace(match: re.Match[str]) -> str:
        ref = match.group(1)
        question_id = ref.strip()
        bucket = captured.get(question_id)
        if not bucket:
            return ""
        if bucket.get("text"):
            return bucket["text"]
        return ", ".join(bucket.get("values", []) or [])

    return _TEMPLATE_REF.sub(_replace, value)


def _next_node_for_branches(
    branches: list[dict[str, Any]],
    match_mode: str,
    captured: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for b in branches or []:
        when = b.get("when")
        if when and _evaluate_condition(when, captured):
            matched.append(b)
            if match_mode != "all":
                break
    return matched


def _severity_label(spec: dict[str, Any], severity_value: str) -> str:
    for field in spec.get("fields", []):
        if field.get("key") != "severity":
            continue
        for opt in field.get("options", []) or []:
            if opt.get("value") == severity_value:
                return opt.get("label", "")
    return severity_value.title() if severity_value else ""


def _classification_command(
    node: dict[str, Any],
    pathway: Pathway,
    note_uuid: str,
    captured: dict[str, dict[str, Any]],
) -> CustomCommand:
    spec = TERMINAL_COMMANDS.get(node.get("command_key") or "") or {}
    params = node.get("params", {}) or {}
    resolved: dict[str, Any] = {}
    for field in spec.get("fields", []):
        key = field["key"]
        resolved[key] = _resolve_template(params.get(key, ""), captured)

    template_context = {
        "pathway_title": pathway.title,
        "title": resolved.get("title", ""),
        "severity": resolved.get("severity", ""),
        "severity_label": _severity_label(spec, resolved.get("severity", "")),
        "body": resolved.get("body", ""),
        "recommended_action": resolved.get("recommended_action", ""),
    }
    html = render_to_string("templates/pathway_classification.html", template_context)
    print_html = render_to_string(
        "templates/pathway_classification_print.html", template_context
    )

    cmd = CustomCommand(
        schema_key=spec.get("schema_key", "pathwayClassification"),
        content=html,
        print_content=print_html,
    )
    cmd.command_uuid = str(uuid4())
    cmd.note_uuid = note_uuid
    return cmd


class PathwayEvaluator(BaseHandler):
    """Advances active pathway runs each time an interview is committed."""

    RESPONDS_TO = EventType.Name(EventType.INTERVIEW_UPDATED)

    def compute(self) -> list[Effect]:
        interview_id = self.event.target.id if self.event and self.event.target else None
        if not interview_id:
            return []
        interview = Interview.objects.filter(id=interview_id).first()
        if not interview:
            return []
        if not interview.committer_id or interview.entered_in_error_id:
            return []

        note_id = interview.note_id
        if not note_id:
            return []
        note = Note.objects.filter(dbid=note_id).first()
        if not note:
            return []
        note_uuid = note.id

        runs = PathwayRun.objects.filter(note_uuid=note_uuid, status="active")
        if not runs.exists():
            return []

        captured = _collect_responses_for_interview(interview)
        interview_questionnaire_ids = {
            str(q.id) for q in interview.questionnaires.all()
        }

        effects: list[Effect] = []
        for run in runs:
            pathway = Pathway.objects.filter(dbid=run.pathway_id).first()
            if not pathway:
                continue
            definition = pathway.definition or {}
            current_node = _find_node(definition.get("root"), run.current_node_id)
            if not current_node or current_node.get("type") != "questionnaire":
                continue
            node_questionnaire_id = str(current_node.get("questionnaire_id") or "")
            if node_questionnaire_id not in interview_questionnaire_ids:
                continue

            # Merge this interview's responses into the run's captured set so
            # later nodes can interpolate against earlier answers.
            merged = dict(run.captured_responses or {})
            merged.update(captured)
            run.captured_responses = merged

            match_mode = current_node.get("match_mode") or "first"
            matched = _next_node_for_branches(
                current_node.get("branches", []) or [], match_mode, merged
            )
            if not matched:
                log.info(
                    "clinical_pathways: no branch matched for node %s in pathway %s",
                    run.current_node_id,
                    pathway.dbid,
                )
                run.status = "completed"
                run.save()
                continue

            new_commands: list[Any] = []
            next_node_id_for_run: str | None = None
            run_completed = False
            for branch in matched:
                then = branch.get("then") or {}
                if then.get("type") == "questionnaire":
                    qid = then.get("questionnaire_id")
                    if not qid:
                        continue
                    cmd = QuestionnaireCommand()
                    cmd.note_uuid = note_uuid
                    cmd.command_uuid = str(uuid4())
                    cmd.questionnaire_id = str(qid)
                    new_commands.append(cmd)
                    if next_node_id_for_run is None:
                        next_node_id_for_run = then.get("node_id", "")
                elif then.get("type") == "terminal":
                    new_commands.append(
                        _classification_command(then, pathway, note_uuid, merged)
                    )
                    run_completed = True

            if not new_commands:
                run.save()
                continue
            effects.append(BatchOriginateCommandEffect(commands=new_commands).apply())
            if run_completed and not next_node_id_for_run:
                run.status = "completed"
            elif next_node_id_for_run:
                run.current_node_id = next_node_id_for_run
            run.save()

        return effects
